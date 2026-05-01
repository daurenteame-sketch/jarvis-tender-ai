"""
ZakupSKScanner — dedicated scanner for zakup.sk.kz (Samruk-Kazyna).

Responsibilities:
  1. Fetch published lots using ZakupSKClient (REST)
  2. Manage incremental scanning via ScanStateManager (page-based)
  3. Deduplicate lots against DB
  4. Download and extract technical specification text from documents
  5. Persist Tender + TenderLot records
  6. Run each new lot through the registered processing pipeline
  7. Record metrics in ScanRun table

zakup.sk.kz specifics:
  - Items are already at the lot level (one REST item = one procurement unit)
  - ZakupSKClient wraps each item into a single-lot announce for API consistency
  - Pagination is page-based (0-indexed)
  - No API auth required for public lots (token optional for extended fields)

Usage:
    scanner = ZakupSKScanner(deduplicator, state_manager)
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
from models.scan_state import ScanState
from integrations.zakupsk.client import ZakupSKClient
from modules.scanner.deduplicator import TenderDeduplicator
from modules.scanner.state_manager import ScanStateManager
from modules.scanner.pipeline import pipeline, PipelineContext
from modules.parser.document_parser import extract_text_from_bytes, truncate_for_ai
from modules.parser.guarantee_filter import looks_like_guarantee_text as _looks_like_guarantee_text

logger = structlog.get_logger(__name__)

PLATFORM = "zakupsk"
MAX_DOCS_PER_LOT = 3
MAX_SPEC_CHARS = 3500


class ZakupSKScanner:
    """
    Self-contained scanner for the zakup.sk.kz platform.

    Designed to be used either:
      - Standalone: stats = await ZakupSKScanner(...).run()
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
        Execute one full ZakupSK scan cycle.
        Returns stats dict with tenders_found, tenders_new, lots_new, profitable_found, errors.
        """
        stats = _empty_stats()

        # Guard: reset if stuck from previous crash
        if await self.state_manager.is_scanning(PLATFORM):
            logger.warning("ZakupSK was marked as scanning — resetting stuck state")
            await self.state_manager.reset_state(PLATFORM)

        await self.state_manager.mark_scan_started(PLATFORM)
        scan_run_id = await self._create_scan_run()

        # Incremental: resume from last saved page
        start_page = await self.state_manager.get_last_offset(PLATFORM)
        logger.info("ZakupSK scan started", start_page=start_page)

        try:
            effective_limit = settings.SCAN_LIMIT if settings.SCAN_LIMIT > 0 else settings.MAX_TENDERS_PER_SCAN
            logger.info("ZakupSK: effective tender limit", limit=effective_limit)
            async with ZakupSKClient() as client:
                async for tender_data in client.stream_published_tenders(
                    max_tenders=effective_limit,
                    start_page=start_page,
                ):
                    stats["tenders_found"] += 1
                    try:
                        result = await self._process_tender(tender_data, client)
                        if result["is_new_tender"]:
                            stats["tenders_new"] += 1
                        stats["lots_found"] += result["lots_found"]
                        stats["lots_new"] += result["lots_new"]
                        stats["profitable_found"] += result["profitable_found"]
                        stats["last_tender_id"] = tender_data.get("external_id")
                    except Exception as exc:
                        stats["errors"] += 1
                        logger.error(
                            "ZakupSK tender processing error",
                            external_id=tender_data.get("external_id", "?"),
                            error=str(exc),
                        )

            # Persist page progress — calculate which page we reached
            page_size = 100
            pages_fetched = (stats["tenders_found"] + page_size - 1) // page_size
            next_page = start_page + pages_fetched
            await self._save_page(next_page)

            await self.state_manager.mark_scan_completed(
                platform=PLATFORM,
                tenders_processed=stats["tenders_found"],
                lots_processed=stats["lots_new"],
                profitable_found=stats["profitable_found"],
                last_tender_id=stats.get("last_tender_id"),
            )
            await self._finish_scan_run(scan_run_id, stats, "completed")
            logger.info("ZakupSK scan completed", **{k: v for k, v in stats.items() if k != "last_tender_id"})

        except Exception as exc:
            logger.error("ZakupSK scan cycle failed", error=str(exc))
            await self.state_manager.mark_scan_failed(PLATFORM, str(exc))
            await self._finish_scan_run(scan_run_id, stats, "failed", error=str(exc))
            raise

        return stats

    # ── Tender processing ─────────────────────────────────────────────────────

    async def _process_tender(self, tender_data: dict, client: ZakupSKClient) -> dict:
        """
        Upsert parent Tender record, then process each contained Lot.
        ZakupSK items are already single-lot announces; lots list has exactly one entry.
        """
        result = {
            "is_new_tender": False,
            "lots_found": len(tender_data.get("lots") or []),
            "lots_new": 0,
            "profitable_found": 0,
        }

        external_id = tender_data["external_id"]

        # Skip if already seen in this run
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

            # Enrich lot with extracted spec text
            lot_data = await self._enrich_with_spec(lot_data, client)

            # Persist lot record
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

    async def _enrich_with_spec(self, lot_data: dict, client: ZakupSKClient) -> dict:
        """
        Download spec documents and extract text into lot_data['technical_spec_text'].
        ZakupSK lots usually have a 'description' field with inline text — we use that too.
        """
        spec_texts: list[str] = []

        description = lot_data.get("description", "")
        if description:
            spec_texts.append(description)

        spec_docs = [
            d for d in (lot_data.get("documents") or [])
            if d.get("is_spec") and d.get("url")
        ][:MAX_DOCS_PER_LOT]

        for doc in spec_docs:
            try:
                content = await client.download_document(doc["url"])
                if content:
                    text = extract_text_from_bytes(content, doc.get("name", ""))
                    if text and len(text) > 50:
                        spec_texts.append(text)
                        doc["extracted"] = True
            except Exception as exc:
                logger.warning("ZakupSK spec extraction failed", url=doc["url"], error=str(exc))

        joined = "\n\n".join(spec_texts)
        # Reject bank-guarantee templates by content. Same guard as in
        # goszakup_scanner — see modules/parser/guarantee_filter.py for why.
        if _looks_like_guarantee_text(joined):
            logger.info(
                "ZakupSK: dropping guarantee-template spec text",
                lot=lot_data.get("external_id"),
                chars=len(joined),
            )
            joined = ""
        lot_data["technical_spec_text"] = truncate_for_ai(joined, MAX_SPEC_CHARS)
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

    async def _save_page(self, page: int) -> None:
        """Persist last scanned page for incremental next run."""
        async with async_session_factory() as session:
            row = await session.execute(
                select(ScanState).where(ScanState.platform == PLATFORM)
            )
            state = row.scalar_one_or_none()
            if state is None:
                state = ScanState(platform=PLATFORM)
                session.add(state)
            state.last_scanned_page = page
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
