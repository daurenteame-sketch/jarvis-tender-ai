"""
ScanStateManager — persists and retrieves incremental scan position per platform.

Allows the scanner to:
  - Resume from where it left off after a restart
  - Track last processed tender ID for deduplication
  - Record scan metrics
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import async_session_factory
from models.scan_state import ScanState

logger = structlog.get_logger(__name__)


class ScanStateManager:
    """Manages persistent scan state in the database."""

    async def get_state(self, platform: str) -> ScanState:
        """Get or create scan state for a platform."""
        async with async_session_factory() as session:
            result = await session.execute(
                select(ScanState).where(ScanState.platform == platform)
            )
            state = result.scalar_one_or_none()
            if state is None:
                state = ScanState(platform=platform)
                session.add(state)
                await session.commit()
                await session.refresh(state)
            return state

    async def get_last_offset(self, platform: str) -> int:
        """Return the last scanned page/offset for a platform."""
        state = await self.get_state(platform)
        return int(state.last_scanned_page or 0)

    async def mark_scan_started(self, platform: str) -> None:
        async with async_session_factory() as session:
            result = await session.execute(
                select(ScanState).where(ScanState.platform == platform)
            )
            state = result.scalar_one_or_none()
            if state is None:
                state = ScanState(platform=platform)
                session.add(state)
            state.is_scanning = True
            state.last_scan_started_at = datetime.now(timezone.utc)
            await session.commit()

    async def mark_scan_completed(
        self,
        platform: str,
        tenders_processed: int,
        lots_processed: int,
        profitable_found: int,
        last_tender_id: Optional[str] = None,
    ) -> None:
        async with async_session_factory() as session:
            result = await session.execute(
                select(ScanState).where(ScanState.platform == platform)
            )
            state = result.scalar_one_or_none()
            if state is None:
                state = ScanState(platform=platform)
                session.add(state)

            now = datetime.now(timezone.utc)
            state.is_scanning = False
            state.last_scan_completed_at = now
            state.last_successful_scan_at = now
            state.error_count = 0
            state.last_error = None

            if last_tender_id:
                state.last_tender_id = last_tender_id

            state.total_tenders_processed = (state.total_tenders_processed or 0) + tenders_processed
            state.total_lots_processed = (state.total_lots_processed or 0) + lots_processed
            state.total_profitable_found = (state.total_profitable_found or 0) + profitable_found

            await session.commit()

        logger.info(
            "Scan state updated",
            platform=platform,
            tenders=tenders_processed,
            lots=lots_processed,
            profitable=profitable_found,
        )

    async def mark_scan_failed(self, platform: str, error: str) -> None:
        async with async_session_factory() as session:
            result = await session.execute(
                select(ScanState).where(ScanState.platform == platform)
            )
            state = result.scalar_one_or_none()
            if state is None:
                state = ScanState(platform=platform)
                session.add(state)
            state.is_scanning = False
            state.error_count = (state.error_count or 0) + 1
            state.last_error = error[:490]
            await session.commit()

    async def is_scanning(self, platform: str) -> bool:
        state = await self.get_state(platform)
        return bool(state.is_scanning)

    async def reset_state(self, platform: str) -> None:
        """Reset scan state (use if stuck in 'scanning' state)."""
        async with async_session_factory() as session:
            result = await session.execute(
                select(ScanState).where(ScanState.platform == platform)
            )
            state = result.scalar_one_or_none()
            if state:
                state.is_scanning = False
                state.last_scanned_page = 0
                await session.commit()
        logger.info("Scan state reset", platform=platform)
