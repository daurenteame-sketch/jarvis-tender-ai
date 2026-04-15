"""
AI Analyzer pipeline step — registers with the scanner pipeline.

This is the bridge between the scanner pipeline and the AI analyzer.
It runs after a lot is persisted to DB and enriches it with AI analysis.
"""
from __future__ import annotations

import asyncio
import structlog
from sqlalchemy import select

from core.config import settings
from core.database import async_session_factory
from models.tender_lot import TenderLot
from models.tender_lot_analysis import TenderLotAnalysis
from modules.scanner.pipeline import ScannerPipeline, PipelineContext
from modules.ai_analyzer.category_classifier import CategoryClassifier
from modules.ai_analyzer.cost_tracker import DevModeLimitError, get_run_guard
from integrations.openai_client.client import OpenAIClient, _ensure_characteristics

logger = structlog.get_logger(__name__)

_classifier = CategoryClassifier()
_ai_client = OpenAIClient()

# Service categories that qualify (whitelist)
QUALIFYING_SERVICE_KEYWORDS = {
    "сайт", "веб", "портал", "приложени", "мобильн",
    "программн", "информационн", "систем", "crm", "erp",
    "автоматизац", "платформ", "чат-бот", "chatbot",
    "искусственн", "разработк", "цифров", "интеграц", "api",
}


async def ai_analysis_step(ctx: PipelineContext) -> None:
    """
    Pipeline step: classify lot category + run AI spec analysis.
    Sets ctx.category and ctx.ai_analysis.
    Stops pipeline (ctx.skip_remaining) if category is 'other'.
    """
    lot_data = ctx.lot_data

    # ── Collect every text source, using tender-level values as fallbacks ──
    title = (
        lot_data.get("title") or
        ctx.tender_data.get("title") or
        ""
    ).strip()

    description = (
        lot_data.get("description") or
        ctx.tender_data.get("description") or   # tender-level description fallback
        ""
    ).strip()

    # Prefer technical_spec_text (AI-ready, truncated).
    # Fall back to raw_spec_text (full untruncated) when the stored AI version
    # is too short — this happens for lots re-analyzed before the limit increase.
    technical_spec = (lot_data.get("technical_spec_text") or "").strip()
    raw_spec       = (lot_data.get("raw_spec_text") or "").strip()

    if len(technical_spec) >= 100:
        spec_text = technical_spec
    elif len(raw_spec) > len(technical_spec):
        spec_text = raw_spec[:10_000]   # cap at 10 000 for AI
        print(
            f"[ai_analysis_step] technical_spec_text too short ({len(technical_spec)} chars) "
            f"— using raw_spec_text ({len(raw_spec)} chars) instead",
            flush=True,
        )
    else:
        spec_text = technical_spec

    # ── Build full_text: single merged input for all AI calls ───────────────
    # Order: title first (short, always present), then description, then spec.
    # Each section is labelled so the AI understands the source.
    full_text_parts: list[str] = []
    if title:
        full_text_parts.append(f"ЗАГОЛОВОК: {title}")
    if description:
        full_text_parts.append(f"ОПИСАНИЕ ЛОТА:\n{description}")
    if spec_text:
        full_text_parts.append(f"ТЕХНИЧЕСКОЕ ЗАДАНИЕ:\n{spec_text}")
    full_text = "\n\n".join(full_text_parts)

    # ── Diagnostic log ───────────────────────────────────────────────────────
    print(
        f"\n{'─'*70}\n"
        f"[ai_analysis_step] lot_id={ctx.lot_id[:8]}\n"
        f"  title        ({len(title):>6} chars): {title[:100]!r}\n"
        f"  description  ({len(description):>6} chars): {description[:100]!r}\n"
        f"  spec_text    ({len(spec_text):>6} chars): {spec_text[:100]!r}\n"
        f"  raw_spec_text({len(raw_spec):>6} chars)\n"
        f"  full_text     {len(full_text):>6} chars total\n"
        f"  preview: {full_text[:300]!r}{'...' if len(full_text) > 300 else ''}\n"
        f"{'─'*70}",
        flush=True,
    )

    if len(full_text) < 50:
        print(
            f"[ai_analysis_step] WARNING: very little text ({len(full_text)} chars)"
            f" — AI will rely on title only",
            flush=True,
        )

    # Step 1: fast keyword classification (no API call)
    quick_category = _classifier.classify_quick(title, description)

    # Step 2: if clearly irrelevant, skip
    if quick_category == "other":
        ctx.category = "other"
        ctx.skip_remaining = True
        await _save_lot_category(ctx.lot_id, "other")
        logger.debug("Lot skipped (other service)", title=title[:60])
        return

    # Step 2b: cache check — if lot already has a saved analysis, reuse it
    existing = await _load_existing_analysis(ctx.lot_id)
    if existing is not None:
        ctx.category = existing.get("category", quick_category)
        ctx.ai_analysis = existing
        logger.debug(
            "Lot skipped — cached analysis reused",
            lot_id=ctx.lot_id[:8],
            category=ctx.category,
        )
        return

    # Step 3: full AI analysis (API call)
    if not settings.OPENAI_API_KEY:
        # No API key — use keyword classification only
        ctx.category = quick_category if quick_category != "uncertain" else "product"
        await _save_lot_category(ctx.lot_id, ctx.category)
        return

    guard = get_run_guard()
    model = settings.OPENAI_MODEL or "gpt-4o"

    # ── Step 3a: product identification — uses full merged text ─────────────
    guard.check_and_increment(model)  # raises DevModeLimitError if limit hit
    if settings.DEV_MODE:
        await asyncio.sleep(settings.DEV_OPENAI_DELAY_S)
    product_id = await _ai_client.identify_product(
        full_text=full_text,    # pre-merged title + description + spec
        title=title,            # kept separately for fallback labelling
        spec_text=spec_text,    # ТЗ alone — AI prompt puts it first; regex targets it
    )

    # ── Step 3b: full AI analysis (category, tech_params, profitability) ────
    guard.check_and_increment(model)  # raises DevModeLimitError if limit hit
    if settings.DEV_MODE:
        await asyncio.sleep(settings.DEV_OPENAI_DELAY_S)
    ai_result = await _ai_client.analyze_tender_specification(
        title=title,
        description=description,
        spec_text=spec_text or description,
    )

    # Unpack two-level identification result
    strict     = product_id.get("strict", {})
    suggestion = product_id.get("ai_suggestion", {})

    # strict fields override the full-analysis results
    ai_result["product_name"]    = strict.get("product_name") or title or ai_result.get("product_name")
    # brand_model: prefer "Brand Model" combo, fallback to model alone
    _brand = (strict.get("brand") or "").strip()
    _model = (strict.get("model") or "").strip()
    ai_result["brand_model"]     = f"{_brand} {_model}".strip() or None
    ai_result["brand"]           = _brand or None
    ai_result["characteristics"] = strict.get("characteristics")  # compact spec string e.g. "2х0,08–4мм², 32A"
    print(
        f"[pipeline_step] characteristics from identify_product: {ai_result['characteristics']!r}",
        flush=True,
    )
    # quantity from strict overrides analyze_tender_specification only when present
    if strict.get("quantity"):
        ai_result["quantity"] = strict["quantity"]

    # new fields from identify_product
    ai_result["product_type"]      = strict.get("product_type")
    ai_result["normalized_name"]   = strict.get("normalized_name")
    ai_result["key_specs"]         = strict.get("key_specs", [])
    ai_result["procurement_hint"]  = strict.get("procurement_hint")
    ai_result["is_standard_based"] = strict.get("is_standard_based", False)
    ai_result["possible_suppliers"] = strict.get("possible_suppliers", [])

    # ai_suggestion fields stored alongside for UI display + supplier search
    # Prefer identify_product suggestion; fall back to exact_product_match from full analysis
    _sugg = suggestion.get("suggested_model")
    if not _sugg:
        _sugg = ai_result.get("exact_product_match")   # from analyze_tender_specification
    ai_result["suggested_model"]       = _sugg
    ai_result["suggestion_confidence"] = suggestion.get("confidence", 0)

    category = ai_result.get("category", quick_category)
    if category not in ("product", "software_service"):
        category = quick_category if quick_category != "uncertain" else "product"

    ctx.category = category
    ctx.ai_analysis = ai_result

    # Save to DB
    if category == "other":
        ctx.skip_remaining = True

    await _save_lot_analysis(ctx.lot_id, category, ai_result, spec_text=spec_text)

    logger.info(
        "Lot AI-analyzed",
        lot_id=ctx.lot_id[:8],
        category=category,
        product=ai_result.get("product_name", "")[:50],
        model=ai_result.get("brand_model") or "—",
        clarity=ai_result.get("spec_clarity", "?"),
    )


async def _save_lot_category(lot_id: str, category: str) -> None:
    """Update only the category field on the lot."""
    import uuid as uuid_mod
    async with async_session_factory() as session:
        result = await session.execute(
            select(TenderLot).where(TenderLot.id == uuid_mod.UUID(lot_id))
        )
        lot = result.scalar_one_or_none()
        if lot:
            lot.category = category
            await session.commit()


async def _save_lot_analysis(
    lot_id: str,
    category: str,
    ai_result: dict,
    spec_text: str = "",
) -> None:
    """Persist lot category + TenderLotAnalysis record."""
    import uuid as uuid_mod
    lot_uuid = uuid_mod.UUID(lot_id)

    async with async_session_factory() as session:
        # Update lot category
        result = await session.execute(select(TenderLot).where(TenderLot.id == lot_uuid))
        lot = result.scalar_one_or_none()
        if lot:
            lot.category = category
            lot.is_analyzed = True

        # Normalize suggestion_confidence: always int 0–100 or None
        raw_conf = ai_result.get("suggestion_confidence")
        norm_conf: int | None = None
        if raw_conf is not None:
            try:
                norm_conf = max(0, min(100, int(raw_conf)))
            except (TypeError, ValueError):
                norm_conf = None

        # Ensure characteristics is never None before saving.
        # Use the actual spec_text for regex scan (richer than ai_summary_ru).
        _scan_text = spec_text or ai_result.get("ai_summary_ru") or ai_result.get("product_name") or ""
        _chars = _ensure_characteristics(
            ai_result.get("characteristics"),
            _scan_text,
            fallback_description=ai_result.get("product_name") or "",
        )
        # Convert empty string to None so DB stores NULL rather than ""
        _chars_db = _chars if _chars else None

        print(
            f"[pipeline_step] Saving characteristics: {_chars_db!r}  "
            f"(lot_id={lot_id[:8]})",
            flush=True,
        )

        # Insert analysis record
        analysis = TenderLotAnalysis(
            lot_id=lot_uuid,
            product_name=ai_result.get("product_name"),
            product_name_en=ai_result.get("product_name_en"),
            brand=ai_result.get("brand") or None,
            brand_model=ai_result.get("brand_model"),          # "Brand Model" combined
            characteristics=_chars_db,   # compact spec string
            suggested_model=ai_result.get("suggested_model") or None,   # AI inference
            suggestion_confidence=norm_conf,                             # 0–100 or None
            dimensions=ai_result.get("dimensions"),
            technical_params=ai_result.get("technical_params", {}),
            materials=ai_result.get("materials"),
            quantity_extracted=ai_result.get("quantity"),
            unit_extracted=ai_result.get("unit"),
            analogs_allowed=ai_result.get("analogs_allowed"),
            spec_clarity=ai_result.get("spec_clarity", "vague"),
            key_requirements=ai_result.get("key_requirements", []),
            ai_summary_ru=ai_result.get("summary_ru", ""),
            is_software_related=ai_result.get("is_software_related", False),
            software_type=ai_result.get("software_type"),
            raw_ai_response=ai_result,
            ai_model=settings.OPENAI_MODEL,
        )
        session.add(analysis)
        await session.commit()


async def _load_existing_analysis(lot_id: str) -> dict | None:
    """
    Return the saved raw_ai_response for this lot if it has already been analyzed,
    or None if no analysis exists yet. Used as a cache to skip redundant API calls.
    """
    import uuid as uuid_mod
    lot_uuid = uuid_mod.UUID(lot_id)
    async with async_session_factory() as session:
        result = await session.execute(
            select(TenderLotAnalysis, TenderLot)
            .join(TenderLot, TenderLotAnalysis.lot_id == TenderLot.id)
            .where(TenderLotAnalysis.lot_id == lot_uuid)
        )
        row = result.first()
        if row is None:
            return None
        analysis, lot = row
        data = dict(analysis.raw_ai_response or {})
        if lot.category:
            data["category"] = lot.category
        return data


def register_ai_step(pipeline: ScannerPipeline) -> None:
    """Register the AI analysis step with the scanner pipeline."""
    pipeline.register("ai_analysis", ai_analysis_step)
