"""
Deduplicator — fast in-memory + DB check to avoid reprocessing tenders/lots.
"""
from __future__ import annotations

from typing import Optional
import structlog
from sqlalchemy import select

from core.database import async_session_factory
from models.tender import Tender
from models.tender_lot import TenderLot

logger = structlog.get_logger(__name__)


class TenderDeduplicator:
    """
    Two-level deduplication:
    1. In-memory cache for the current scan run (O(1) lookups)
    2. Database check for tenders seen in previous scans
    """

    def __init__(self):
        # Cache sets populated during a scan run
        self._seen_tender_keys: set[str] = set()
        self._seen_lot_keys: set[str] = set()

    def _tender_key(self, platform: str, external_id: str) -> str:
        return f"{platform}:{external_id}"

    def _lot_key(self, platform: str, lot_external_id: str) -> str:
        return f"{platform}:lot:{lot_external_id}"

    def reset(self) -> None:
        """Clear in-memory cache (call at the start of each scan run)."""
        self._seen_tender_keys.clear()
        self._seen_lot_keys.clear()

    async def is_tender_new(self, platform: str, external_id: str) -> bool:
        """
        Returns True if this tender has NOT been seen before.
        Checks memory first, then DB.
        """
        key = self._tender_key(platform, external_id)
        if key in self._seen_tender_keys:
            return False

        async with async_session_factory() as session:
            result = await session.execute(
                select(Tender.id).where(
                    Tender.platform == platform,
                    Tender.external_id == external_id,
                )
            )
            exists = result.scalar_one_or_none() is not None

        if exists:
            self._seen_tender_keys.add(key)
        return not exists

    async def is_lot_new(self, platform: str, lot_external_id: str) -> bool:
        """Returns True if this lot has NOT been seen before."""
        key = self._lot_key(platform, lot_external_id)
        if key in self._seen_lot_keys:
            return False

        async with async_session_factory() as session:
            result = await session.execute(
                select(TenderLot.id).where(
                    TenderLot.platform == platform,
                    TenderLot.lot_external_id == lot_external_id,
                )
            )
            exists = result.scalar_one_or_none() is not None

        if exists:
            self._seen_lot_keys.add(key)
        return not exists

    def mark_tender_seen(self, platform: str, external_id: str) -> None:
        self._seen_tender_keys.add(self._tender_key(platform, external_id))

    def mark_lot_seen(self, platform: str, lot_external_id: str) -> None:
        self._seen_lot_keys.add(self._lot_key(platform, lot_external_id))
