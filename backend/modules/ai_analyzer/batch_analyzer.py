"""
Batch AI Analyzer.

Fetches unanalyzed lots from the DB and runs ai_analysis_step on each.
Exposes progress state for live polling (same pattern as recalculate.py).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

import structlog
from sqlalchemy import select, func

from core.config import settings
from core.database import async_session_factory
from models.tender import Tender
from models.tender_lot import TenderLot
from modules.ai_analyzer.cost_tracker import (
    get_mode_limit, estimate_cost, get_tracker, get_run_guard,
    DevModeLimitError, ANALYZE_MODES,
)
from modules.scanner.pipeline import PipelineContext

logger = structlog.get_logger(__name__)


# ── Progress state ─────────────────────────────────────────────────────────────

@dataclass
class AnalyzeProgress:
    running: bool = False
    total: int = 0
    done: int = 0
    skipped: int = 0
    errors: int = 0
    finished: bool = False
    mode: str = ""
    cost_estimate_usd: float = 0.0
    cost_actual_usd: float = 0.0
    model: str = ""
    error_message: Optional[str] = None


_progress = AnalyzeProgress()


def get_progress() -> dict:
    p = _progress
    return {
        "running":           p.running,
        "total":             p.total,
        "done":              p.done,
        "skipped":           p.skipped,
        "errors":            p.errors,
        "finished":          p.finished,
        "mode":              p.mode,
        "cost_estimate_usd": p.cost_estimate_usd,
        "cost_actual_usd":   round(p.cost_actual_usd, 4),
        "model":             p.model,
        "error_message":     p.error_message,
        "pct": round(p.done / p.total * 100, 1) if p.total else 0,
    }


# ── Estimate (no DB write) ─────────────────────────────────────────────────────

def _effective_limit(mode: str) -> int:
    """Mode limit capped by SCAN_LIMIT and DEV_MAX_LOTS_PER_RUN when in dev mode."""
    mode_limit = get_mode_limit(mode)
    caps = [mode_limit]
    if settings.SCAN_LIMIT > 0:
        caps.append(settings.SCAN_LIMIT)
    if settings.DEV_MODE:
        caps.append(settings.DEV_MAX_LOTS_PER_RUN)
    return min(caps)


async def get_estimate(mode: str) -> dict:
    """
    Count unanalyzed lots and return cost estimate — no side effects.
    Called before the user confirms the run.
    """
    limit = _effective_limit(mode)
    model = settings.OPENAI_MODEL or "gpt-4o"

    async with async_session_factory() as session:
        total_unanalyzed = (
            await session.execute(
                select(func.count(TenderLot.id)).where(TenderLot.is_analyzed == False)  # noqa
            )
        ).scalar() or 0

    will_analyze = min(total_unanalyzed, limit)
    cost = estimate_cost(will_analyze, model)

    return {
        "mode":              mode,
        "mode_limit":        limit,
        "scan_limit":        settings.SCAN_LIMIT,
        "total_unanalyzed":  total_unanalyzed,
        "will_analyze":      will_analyze,
        "cost_estimate_usd": cost,
        "model":             model,
        "modes":             {k: v for k, v in ANALYZE_MODES.items()},
    }


# ── Main batch loop ────────────────────────────────────────────────────────────

async def run_batch_analysis(
    mode: str = "standard",
    budget_min: Optional[float] = None,
) -> None:
    """
    Analyze up to `limit` unanalyzed lots.
    If budget_min is set, only selects lots with budget >= budget_min,
    ordered by budget DESC (highest value first).
    Updates _progress in-place so the API can poll status.
    """
    global _progress
    from modules.ai_analyzer.pipeline_step import ai_analysis_step

    limit  = _effective_limit(mode)
    model  = settings.OPENAI_MODEL or "gpt-4o"
    cost_e = estimate_cost(limit, model)

    # Reset per-run budget guard so limits apply fresh to this run
    guard = get_run_guard()
    guard.reset()

    if settings.DEV_MODE:
        logger.info(
            "DEV MODE active",
            max_lots=limit,
            max_openai_requests=settings.DEV_MAX_OPENAI_REQUESTS_PER_RUN,
            soft_budget_usd=settings.DEV_BUDGET_SOFT_USD,
            hard_budget_usd=settings.DEV_BUDGET_HARD_USD,
            delay_s=settings.DEV_OPENAI_DELAY_S,
        )

    _progress = AnalyzeProgress(
        running=True,
        mode=mode,
        cost_estimate_usd=cost_e,
        model=model,
    )

    # Track lot IDs processed this run to prevent any within-run duplicates
    _seen_lot_ids: set[str] = set()

    try:
        # Fetch unanalyzed lots — priority mode sorts by budget DESC
        async with async_session_factory() as session:
            q = (
                select(TenderLot, Tender)
                .join(Tender, TenderLot.tender_id == Tender.id)
                .where(TenderLot.is_analyzed == False)  # noqa
            )
            if budget_min is not None:
                q = q.where(TenderLot.budget >= budget_min)
            if mode == "priority" or budget_min is not None:
                q = q.order_by(TenderLot.budget.desc())
            else:
                q = q.order_by(TenderLot.first_seen_at.desc())
            q = q.limit(limit)
            rows = await session.execute(q)
            pairs = rows.all()

        _progress.total = len(pairs)
        logger.info("Batch AI analysis started", total=_progress.total, mode=mode, model=model)

        if not pairs:
            _progress.finished = True
            return

        for lot, tender in pairs:
            lot_id_str = str(lot.id)

            # Within-run dedup (should not happen via DB filter, but guard just in case)
            if lot_id_str in _seen_lot_ids:
                logger.debug("Batch analysis: duplicate lot skipped", lot_id=lot_id_str[:8])
                continue
            _seen_lot_ids.add(lot_id_str)

            try:
                ctx = PipelineContext(
                    tender_data={
                        "title":       tender.title or "",
                        "description": tender.description or "",
                    },
                    lot_data={
                        "title":               lot.title or "",
                        "description":         lot.description or "",
                        "technical_spec_text": lot.technical_spec_text or "",
                        "raw_spec_text":       getattr(lot, "raw_spec_text", None) or "",
                    },
                    tender_id=str(tender.id),
                    lot_id=lot_id_str,
                    platform=lot.platform or "",
                )

                await ai_analysis_step(ctx)

                if ctx.category == "other":
                    _progress.skipped += 1

            except DevModeLimitError as exc:
                # Hard limit hit — stop entire run gracefully
                _progress.error_message = str(exc)
                logger.warning("Batch analysis stopped by DEV_MODE limit", reason=str(exc))
                break

            except Exception as exc:
                _progress.errors += 1
                logger.error(
                    "Batch analysis: lot failed",
                    lot_id=lot_id_str[:8],
                    error=str(exc),
                )
            finally:
                _progress.done += 1

            # Yield control between lots to keep event loop responsive
            await asyncio.sleep(0)

        actual_cost = get_tracker().record_run(
            lots_processed=_progress.done,
            model=model,
            mode=mode,
        )
        _progress.cost_actual_usd = actual_cost
        _progress.finished = True

        # ── Summary log ───────────────────────────────────────────────────────
        guard_stats = guard.summary()
        logger.info(
            "Batch AI analysis finished",
            lots_processed=_progress.done,
            lots_skipped=_progress.skipped,
            errors=_progress.errors,
            openai_requests=guard_stats["openai_requests"],
            cost_estimate_usd=guard_stats["cost_estimate_usd"],
            cost_actual_usd=actual_cost,
            dev_mode=settings.DEV_MODE,
            hard_stopped=guard_stats["hard_stopped"],
        )
        print(
            f"\n{'═'*60}\n"
            f"  AI BATCH ANALYSIS COMPLETE\n"
            f"  Лотов обработано : {_progress.done} / {_progress.total}\n"
            f"  Пропущено        : {_progress.skipped} (other/cached)\n"
            f"  Ошибок           : {_progress.errors}\n"
            f"  OpenAI запросов  : {guard_stats['openai_requests']}\n"
            f"  Стоимость (оценка): ${guard_stats['cost_estimate_usd']:.4f}\n"
            f"  Стоимость (факт) : ${actual_cost:.4f}\n"
            + (f"  ⚠ DEV MODE — остановлен лимитом\n" if guard_stats["hard_stopped"] else "")
            + f"{'═'*60}\n",
            flush=True,
        )

    except Exception as exc:
        _progress.error_message = str(exc)
        logger.error("Batch analysis crashed", error=str(exc))
    finally:
        _progress.running = False
