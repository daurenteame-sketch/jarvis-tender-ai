"""
Notification pipeline step — sends Telegram alerts for profitable lots.

Runs after the profitability step. Checks ctx.profitability.is_profitable and,
if True, sends a rich Telegram message with the full financial breakdown.
Also marks TenderLot.notification_sent = True to prevent duplicate alerts.
"""
from __future__ import annotations

from typing import Optional
import structlog
from sqlalchemy import select

from core.database import async_session_factory
from modules.scanner.pipeline import ScannerPipeline, PipelineContext

logger = structlog.get_logger(__name__)

_notifier: Optional[object] = None


def _get_notifier():
    global _notifier
    if _notifier is None:
        from modules.notifications.telegram import TelegramNotifier
        _notifier = TelegramNotifier()
    return _notifier


async def notification_step(ctx: PipelineContext) -> None:
    """
    Pipeline step: send Telegram notification if lot is profitable AND
    matches the user's saved filter preferences (category, keywords, budget, margin).
    """
    profitability = ctx.profitability
    if not profitability or not profitability.get("is_profitable"):
        return

    # Check notification_sent flag to avoid duplicates
    if await _is_already_notified(ctx.lot_id):
        logger.debug("Notification already sent, skipping", lot_id=ctx.lot_id[:8])
        return

    notifier = _get_notifier()
    notified = await notifier.send_to_all_matching_users(
        tender_data=ctx.tender_data,
        lot_data=ctx.lot_data,
        lot_id=ctx.lot_id,
        profitability=profitability,
    )

    if notified > 0:
        await _mark_notified(ctx.lot_id)
        logger.info("Notification sent for profitable lot", lot_id=ctx.lot_id[:8], users=notified)


async def _passes_user_filters(ctx: PipelineContext) -> bool:
    """
    Check lot against all active company filter settings.
    Returns True (notify) or False (skip).
    Falls back to True if no settings are configured or DB unavailable.
    """
    try:
        from sqlalchemy import select
        from models.company import Company

        async with async_session_factory() as session:
            # Use the first (and only) active company for now.
            # When multi-tenancy is added, match company by lot ownership.
            result = await session.execute(
                select(Company).where(Company.is_active == True).limit(1)
            )
            company = result.scalar_one_or_none()

        if not company or not company.settings:
            return True

        f = company.settings.get("filters", {})
        notif = company.settings.get("notifications", {})

        lot = ctx.lot_data
        profitability = ctx.profitability or {}

        # ── Telegram notifications enabled? ──
        if not notif.get("telegram", True):
            return False

        # ── Min profit threshold ──
        min_profit = notif.get("min_profit_for_notify", 0)
        net_profit = profitability.get("net_profit_kzt", 0) or 0
        if min_profit and net_profit < min_profit:
            logger.debug(
                "Lot below min profit threshold",
                lot_id=ctx.lot_id[:8],
                net_profit=net_profit,
                threshold=min_profit,
            )
            return False

        # ── Platform filter ──
        allowed_platforms = f.get("platforms", [])
        if allowed_platforms and lot.get("platform") not in allowed_platforms:
            return False

        # ── Category filter ──
        allowed_categories = f.get("categories", [])
        if allowed_categories and lot.get("category") not in allowed_categories:
            return False

        # ── Budget filter ──
        budget = float(lot.get("budget") or 0)
        min_budget = f.get("min_budget")
        max_budget = f.get("max_budget")
        if min_budget and budget < min_budget:
            return False
        if max_budget and budget > max_budget:
            return False

        # ── Margin filter ──
        min_margin = f.get("min_margin")
        if min_margin:
            margin = float(profitability.get("profit_margin_percent", 0) or 0)
            if margin < min_margin:
                return False

        # ── Keyword filter (include) ──
        keywords = f.get("keywords", [])
        if keywords:
            title_lower = (lot.get("title") or "").lower()
            desc_lower = (lot.get("description") or "").lower()
            text = title_lower + " " + desc_lower
            if not any(kw.lower() in text for kw in keywords):
                return False

        # ── Keyword filter (exclude) ──
        exclude_keywords = f.get("exclude_keywords", [])
        if exclude_keywords:
            title_lower = (lot.get("title") or "").lower()
            desc_lower = (lot.get("description") or "").lower()
            text = title_lower + " " + desc_lower
            if any(kw.lower() in text for kw in exclude_keywords):
                return False

        return True

    except Exception as exc:
        logger.warning("Filter check failed, defaulting to notify", error=str(exc))
        return True


async def _is_already_notified(lot_id: str) -> bool:
    import uuid as uuid_mod
    from models.tender_lot import TenderLot
    async with async_session_factory() as session:
        row = await session.execute(
            select(TenderLot).where(TenderLot.id == uuid_mod.UUID(lot_id))
        )
        lot = row.scalar_one_or_none()
        return bool(lot and lot.notification_sent)


async def _mark_notified(lot_id: str) -> None:
    import uuid as uuid_mod
    from models.tender_lot import TenderLot
    async with async_session_factory() as session:
        row = await session.execute(
            select(TenderLot).where(TenderLot.id == uuid_mod.UUID(lot_id))
        )
        lot = row.scalar_one_or_none()
        if lot:
            lot.notification_sent = True
            await session.commit()


def register_notification_step(pipeline: ScannerPipeline) -> None:
    pipeline.register("notification", notification_step)
