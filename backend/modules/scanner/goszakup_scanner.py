"""
GosZakupScanner — dedicated scanner for goszakup.gov.kz.

Responsibilities:
  1. Fetch published tenders using GosZakupClient (GraphQL)
  2. Manage incremental scanning via ScanStateManager (offset-based)
  3. Deduplicate tenders and lots against DB
  4. Download and extract technical specification text from documents
  5. Persist Tender + TenderLot records
  6. Run each new lot through the registered processing pipeline
  7. Record metrics in ScanRun table

Usage:
    scanner = GosZakupScanner(deduplicator, state_manager)
    stats = await scanner.run()
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional
import structlog
from sqlalchemy import select

from core.database import async_session_factory
from core.config import settings
from models.tender import Tender
from models.tender_lot import TenderLot
from models.scan_run import ScanRun
from integrations.goszakup.client import GosZakupClient
from integrations.goszakup.web_scraper import GosZakupWebScraper
from modules.scanner.deduplicator import TenderDeduplicator
from modules.scanner.state_manager import ScanStateManager
from modules.scanner.pipeline import pipeline, PipelineContext
from modules.parser.document_parser import extract_text_from_bytes, truncate_for_ai, strip_kazakh_lines

logger = structlog.get_logger(__name__)

PLATFORM = "goszakup"
MAX_DOCS_PER_LOT = 3
MAX_SPEC_CHARS   = 10_000   # stored in technical_spec_text (AI-ready, truncated)
MAX_RAW_CHARS    = 50_000   # stored in raw_spec_text (full text, for debugging)


class GosZakupScanner:
    """
    Self-contained scanner for the goszakup.gov.kz platform.

    Designed to be used either:
      - Standalone: stats = await GosZakupScanner(...).run()
      - Via TenderScanner which coordinates both platform scanners
    """

    def __init__(
        self,
        deduplicator: TenderDeduplicator,
        state_manager: ScanStateManager,
    ) -> None:
        self.deduplicator = deduplicator
        self.state_manager = state_manager

    # ── Public entrypoint ─────────────────────────────────────────────────────

    async def run(self) -> dict:
        """
        Execute one full GosZakup scan cycle.
        Returns stats dict with tenders_found, tenders_new, lots_new, profitable_found, errors.
        """
        stats = _empty_stats()

        # Guard: reset if stuck from previous crash
        if await self.state_manager.is_scanning(PLATFORM):
            logger.warning("GosZakup was marked as scanning — resetting stuck state")
            await self.state_manager.reset_state(PLATFORM)

        await self.state_manager.mark_scan_started(PLATFORM)
        scan_run_id = await self._create_scan_run()

        # Incremental: resume from last successful offset
        start_offset = await self.state_manager.get_last_offset(PLATFORM)
        logger.info("GosZakup scan started", start_offset=start_offset)

        try:
            use_api = bool(
                settings.GOSZAKUP_API_TOKEN
                and not settings.GOSZAKUP_API_TOKEN.startswith("your_")
            )

            # Effective limit: SCAN_LIMIT when set (>0), else MAX_TENDERS_PER_SCAN
            effective_limit = settings.SCAN_LIMIT if settings.SCAN_LIMIT > 0 else settings.MAX_TENDERS_PER_SCAN
            logger.info("GosZakup: effective tender limit", limit=effective_limit)

            if use_api:
                logger.info("GosZakup: using GraphQL API")
                stream = self._stream_via_api(start_offset, stats, effective_limit)
            else:
                logger.info("GosZakup: API token not set — using public web scraper")
                max_pages = max(1, effective_limit // 50 + 1)
                stream = self._stream_via_scraper(start_page=max(1, start_offset // 50 + 1), max_pages=max_pages, stats=stats)

            async for tender_data in stream:
                try:
                    result = await self._process_tender(tender_data)
                    if result["is_new_tender"]:
                        stats["tenders_new"] += 1
                    stats["lots_found"] += result["lots_found"]
                    stats["lots_new"] += result["lots_new"]
                    stats["profitable_found"] += result["profitable_found"]
                    stats["last_tender_id"] = tender_data.get("external_id")
                except Exception as exc:
                    stats["errors"] += 1
                    logger.error(
                        "GosZakup tender processing error",
                        external_id=tender_data.get("external_id", "?"),
                        error=str(exc),
                    )

            # Persist progress
            next_offset = start_offset + stats["tenders_found"]
            await self._save_offset(next_offset)

            await self.state_manager.mark_scan_completed(
                platform=PLATFORM,
                tenders_processed=stats["tenders_found"],
                lots_processed=stats["lots_new"],
                profitable_found=stats["profitable_found"],
                last_tender_id=stats.get("last_tender_id"),
            )
            await self._finish_scan_run(scan_run_id, stats, "completed")
            logger.info("GosZakup scan completed", **{k: v for k, v in stats.items() if k != "last_tender_id"})

        except Exception as exc:
            logger.error("GosZakup scan cycle failed", error=str(exc))
            await self.state_manager.mark_scan_failed(PLATFORM, str(exc))
            await self._finish_scan_run(scan_run_id, stats, "failed", error=str(exc))
            raise

        return stats

    # ── Stream helpers ────────────────────────────────────────────────────────

    async def _stream_via_api(self, start_offset: int, stats: dict, limit: int = 20):
        async with GosZakupClient() as client:
            async for tender_data in client.stream_published_tenders(
                max_tenders=limit,
                start_offset=start_offset,
            ):
                stats["tenders_found"] += 1
                # Enrich each lot with spec text while we still have the client
                for i, lot_data in enumerate(tender_data.get("lots") or []):
                    tender_data["lots"][i] = await self._enrich_with_spec(lot_data, client)
                yield tender_data

    async def _stream_via_scraper(self, start_page: int, max_pages: int, stats: dict):
        async with GosZakupWebScraper() as scraper:
            async for tender_data in scraper.stream_published_tenders(
                max_pages=max_pages,
                start_page=start_page,
            ):
                stats["tenders_found"] += 1
                # Enrich each lot with spec text — same as the API path
                for i, lot_data in enumerate(tender_data.get("lots") or []):
                    tender_data["lots"][i] = await self._enrich_with_spec(lot_data, scraper)
                yield tender_data

    # ── Tender processing ─────────────────────────────────────────────────────

    async def _process_tender(self, tender_data: dict) -> dict:
        """Upsert parent Tender, then process each contained Lot."""
        result = {
            "is_new_tender": False,
            "lots_found": len(tender_data.get("lots") or []),
            "lots_new": 0,
            "profitable_found": 0,
        }

        external_id = tender_data["external_id"]

        # Skip if we've seen this tender already in this run
        if not await self.deduplicator.is_tender_new(PLATFORM, external_id):
            return result

        tender_id, is_new = await self._upsert_tender(tender_data)
        result["is_new_tender"] = is_new

        lots = tender_data.get("lots") or []
        if not lots:
            return result

        lot_contexts: list[PipelineContext] = []

        for lot_data in lots:
            lot_ext_id = lot_data.get("lot_external_id", "")
            if not lot_ext_id:
                continue

            if not await self.deduplicator.is_lot_new(PLATFORM, lot_ext_id):
                continue

            result["lots_new"] += 1

            # Persist lot
            lot_id = await self._create_lot(tender_id, tender_data, lot_data)
            self.deduplicator.mark_lot_seen(PLATFORM, lot_ext_id)

            lot_contexts.append(PipelineContext(
                tender_data=tender_data,
                lot_data=lot_data,
                tender_id=str(tender_id),
                lot_id=str(lot_id),
                platform=PLATFORM,
            ))

        # Run pipeline (AI → supplier → profitability) with limited concurrency
        if lot_contexts:
            completed = await pipeline.run_batch(lot_contexts, concurrency=2)
            for ctx in completed:
                if ctx.profitability and ctx.profitability.get("is_profitable"):
                    result["profitable_found"] += 1

        return result

    # ── Document enrichment ───────────────────────────────────────────────────

    async def _enrich_with_spec(self, lot_data: dict, client) -> dict:
        """
        Download spec documents and extract text.

        Stores two fields on lot_data:
          technical_spec_text — AI-ready text, truncated to MAX_SPEC_CHARS
          raw_spec_text       — full concatenated extraction, up to MAX_RAW_CHARS (debug)
        """
        raw_parts: list[str] = []
        lot_id_log = lot_data.get("lot_external_id") or "?"

        # Always include the lot description as the first chunk
        description = (lot_data.get("description") or "").strip()
        if description:
            raw_parts.append(f"[ОПИСАНИЕ ЛОТА]\n{description}")

        all_docs  = lot_data.get("documents") or []
        spec_docs = [d for d in all_docs if d.get("is_spec") and d.get("url")][:MAX_DOCS_PER_LOT]
        pdf_docs  = [d for d in spec_docs if (d.get("extension") or "").lower() == ".pdf"
                     or d.get("name", "").lower().endswith(".pdf")]

        print(
            f"\n[enrich_with_spec] lot={lot_id_log!r} | "
            f"total_docs={len(all_docs)} spec_docs={len(spec_docs)} pdf_docs={len(pdf_docs)}",
            flush=True,
        )
        if not spec_docs:
            print(
                f"[enrich_with_spec] ⚠️  NO SPEC DOCUMENTS for lot={lot_id_log!r} — "
                f"AI will rely on title/description only",
                flush=True,
            )

        for doc in spec_docs:
            url  = doc.get("url", "")
            name = doc.get("name", "")
            ext  = (doc.get("extension") or "").lower()
            is_pdf = ext == ".pdf" or name.lower().endswith(".pdf")

            if is_pdf:
                print(f"\n[PDF FOUND]: {name!r}  url={url}", flush=True)

            try:
                content = await client.download_document(url)
                if not content:
                    logger.warning("GosZakup: empty document", url=url)
                    if is_pdf:
                        print(f"[PDF EMPTY]: download returned nothing for {name!r}", flush=True)
                    continue

                text = extract_text_from_bytes(content, name)
                extracted_len = len(text) if text else 0

                if is_pdf:
                    if not text or extracted_len == 0:
                        print(f"[PDF EMPTY]: no text extracted from {name!r} ({len(content)}B)", flush=True)
                    else:
                        print(
                            f"[PDF TEXT LENGTH]: {extracted_len} chars  file={name!r}\n"
                            f"[PDF PREVIEW]: {text[:300]!r}",
                            flush=True,
                        )
                else:
                    print(
                        f"[enrich_with_spec] doc={name!r} size={len(content)}B "
                        f"extracted={extracted_len} chars",
                        flush=True,
                    )

                if text and extracted_len > 100:
                    raw_parts.append(f"[ДОКУМЕНТ: {name}]\n{text}")
                    doc["extracted"] = True
                    doc["extracted_chars"] = extracted_len
                else:
                    logger.warning(
                        "GosZakup: document too short to use",
                        url=url, chars=extracted_len,
                    )

            except Exception as exc:
                logger.warning("GosZakup spec extraction failed", url=url, error=str(exc))
                if is_pdf:
                    print(f"[PDF EMPTY]: exception during extraction of {name!r}: {exc}", flush=True)

        raw_full = "\n\n".join(raw_parts)
        raw_full = strip_kazakh_lines(raw_full)

        tech_text = truncate_for_ai(raw_full, MAX_SPEC_CHARS)

        # ── Summary: verify technical_spec_text is not empty ────────────────
        if not raw_full.strip():
            print(
                f"\n[enrich_with_spec] ⚠️  EMPTY — lot={lot_id_log!r} "
                f"docs={len(spec_docs)} — no text extracted from any document",
                flush=True,
            )
        else:
            print(
                f"\n{'─'*70}\n"
                f"[enrich_with_spec] lot={lot_id_log!r} | docs={len(spec_docs)}\n"
                f"  raw_full   : {len(raw_full):>7} chars\n"
                f"  tech_text  : {len(tech_text):>7} chars (AI-ready, truncated)\n"
                f"  PREVIEW (first 1000 chars):\n"
                f"{raw_full[:1000]}\n"
                f"{'─'*70}",
                flush=True,
            )

        lot_data["technical_spec_text"] = tech_text
        lot_data["raw_spec_text"] = raw_full[:MAX_RAW_CHARS] if raw_full else ""
        return lot_data

    # ── DB helpers ────────────────────────────────────────────────────────────

    async def _upsert_tender(self, data: dict) -> tuple:
        """Insert or update Tender. Returns (tender_id, is_new)."""
        async with async_session_factory() as session:
            row = await session.execute(
                select(Tender).where(
                    Tender.platform == PLATFORM,
                    Tender.external_id == data["external_id"],
                )
            )
            tender = row.scalar_one_or_none()
            is_new = tender is None

            if is_new:
                tender = Tender(
                    platform=PLATFORM,
                    external_id=data["external_id"],
                    status=data.get("status", "published"),
                    title=data.get("title") or "(без названия)",
                    description=data.get("description", ""),
                    procurement_method=data.get("procurement_method", ""),
                    budget=data.get("budget"),
                    currency=data.get("currency", "KZT"),
                    customer_name=data.get("customer_name", ""),
                    customer_bin=data.get("customer_bin", ""),
                    customer_region=data.get("customer_region", ""),
                    documents=data.get("documents", []),
                    raw_data=data.get("raw_data", {}),
                    first_seen_at=datetime.now(timezone.utc),
                )
                _set_dt(tender, "published_at", data.get("published_at"))
                _set_dt(tender, "deadline_at", data.get("deadline_at"))
                session.add(tender)
                self.deduplicator.mark_tender_seen(PLATFORM, data["external_id"])
            else:
                tender.status = data.get("status", tender.status)
                if data.get("deadline_at"):
                    _set_dt(tender, "deadline_at", data["deadline_at"])

            await session.commit()
            await session.refresh(tender)
            return tender.id, is_new

    async def _create_lot(self, tender_id, tender_data: dict, lot_data: dict):
        """Insert TenderLot. Returns lot.id."""
        async with async_session_factory() as session:
            lot = TenderLot(
                tender_id=tender_id,
                platform=PLATFORM,
                lot_external_id=lot_data["lot_external_id"],
                title=lot_data.get("title") or tender_data.get("title") or "(без названия)",
                description=lot_data.get("description", ""),
                technical_spec_text=lot_data.get("technical_spec_text", ""),
                raw_spec_text=lot_data.get("raw_spec_text", ""),
                quantity=lot_data.get("quantity"),
                unit=lot_data.get("unit", "шт"),
                budget=lot_data.get("budget") or tender_data.get("budget"),
                currency=lot_data.get("currency", "KZT"),
                status="published",
                documents=lot_data.get("documents", []),
                raw_data=lot_data.get("raw_data", {}),
                first_seen_at=datetime.now(timezone.utc),
            )
            _set_dt(lot, "deadline_at", tender_data.get("deadline_at"))
            session.add(lot)
            await session.commit()
            await session.refresh(lot)
            return lot.id

    async def _save_offset(self, offset: int) -> None:
        """Persist last scanned offset for incremental next run."""
        from models.scan_state import ScanState
        async with async_session_factory() as session:
            row = await session.execute(
                select(ScanState).where(ScanState.platform == PLATFORM)
            )
            state = row.scalar_one_or_none()
            if state:
                state.last_scanned_page = offset
                await session.commit()

    async def _create_scan_run(self) -> object:
        async with async_session_factory() as session:
            run = ScanRun(platform=PLATFORM, status="running")
            session.add(run)
            await session.commit()
            await session.refresh(run)
            return run.id

    async def _finish_scan_run(
        self,
        run_id,
        stats: dict,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        async with async_session_factory() as session:
            row = await session.execute(select(ScanRun).where(ScanRun.id == run_id))
            run = row.scalar_one_or_none()
            if run:
                run.status = status
                run.completed_at = datetime.now(timezone.utc)
                run.tenders_found = stats.get("tenders_found", 0)
                run.tenders_new = stats.get("tenders_new", 0)
                run.profitable_found = stats.get("profitable_found", 0)
                if error:
                    run.error_message = error[:500]
                await session.commit()


# ── Utilities ─────────────────────────────────────────────────────────────────

def _empty_stats() -> dict:
    return {
        "tenders_found": 0,
        "tenders_new": 0,
        "lots_found": 0,
        "lots_new": 0,
        "profitable_found": 0,
        "errors": 0,
        "last_tender_id": None,
    }


def _set_dt(obj, field: str, value) -> None:
    if not value:
        return
    if isinstance(value, datetime):
        setattr(obj, field, value)
        return
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        setattr(obj, field, dt)
    except (ValueError, TypeError) as exc:
        logger.warning("Failed to parse datetime", field=field, value=value, error=str(exc))
