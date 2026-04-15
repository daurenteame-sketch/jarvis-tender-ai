"""
Subscription guard dependency.

Usage:
    from core.subscription_guard import require_paid_plan, check_lot_view_limit

    @router.get("/lots/{id}")
    async def get_lot(id: str, _: None = Depends(check_lot_view_limit)):
        ...

Free plan limits:
    - lots_per_day: 20  (lot detail views per day, tracked in user_actions)
"""
from __future__ import annotations

from datetime import datetime, timezone, date
from typing import Optional

from fastapi import Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.deps import get_current_user
from models.company import Company
from models.user import User
from models.user_action import UserAction

FREE_LOT_DETAIL_LIMIT = 20  # lot detail views per day on free plan


def _resolve_plan(company: Company) -> str:
    """Return effective plan, auto-downgrading expired trial/pro."""
    plan = company.subscription_plan or "free"
    if plan in ("trial", "pro"):
        settings_data = company.settings or {}
        expires_raw = settings_data.get("subscription_expires_at")
        if expires_raw:
            try:
                expires_at = datetime.fromisoformat(expires_raw)
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if expires_at < datetime.now(timezone.utc):
                    return "free"
            except (ValueError, TypeError):
                pass
    return plan


async def require_paid_plan(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Raises 402 if the user is on the free plan."""
    result = await db.execute(select(Company).where(Company.id == current_user.company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    plan = _resolve_plan(company)
    if plan == "free":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "subscription_required",
                "message": "Эта функция доступна только на тарифе Pro. Активируйте пробный период или обновите тариф.",
                "upgrade_url": "https://t.me/jarvis_tender_kz",
            },
        )
    return current_user


async def check_lot_view_limit(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    For free plan users: track lot detail views per day.
    Raises 402 when the daily limit is exceeded.
    Paid plans pass through without DB hit.
    """
    result = await db.execute(select(Company).where(Company.id == current_user.company_id))
    company = result.scalar_one_or_none()
    if not company:
        return current_user

    plan = _resolve_plan(company)
    if plan != "free":
        return current_user  # no limit for paid plans

    # Count "viewed" actions today for this user
    today_start = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)
    count_result = await db.execute(
        select(func.count(UserAction.id)).where(
            UserAction.user_id == current_user.id,
            UserAction.action == "viewed",
            UserAction.created_at >= today_start,
        )
    )
    views_today: int = count_result.scalar_one() or 0

    if views_today >= FREE_LOT_DETAIL_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "daily_limit_exceeded",
                "message": (
                    f"Вы просмотрели {views_today} лотов сегодня. "
                    f"Лимит бесплатного тарифа: {FREE_LOT_DETAIL_LIMIT} лотов/день. "
                    "Активируйте Pro для безлимитного доступа."
                ),
                "views_today": views_today,
                "limit": FREE_LOT_DETAIL_LIMIT,
                "upgrade_url": "https://t.me/jarvis_tender_kz",
            },
        )
    return current_user
