"""
User settings & subscription API.

Endpoints:
  GET  /users/me/settings     — get current user's filter preferences
  PUT  /users/me/settings     — update filter preferences (stored in company.settings)
  GET  /users/me/subscription — get subscription plan info
  POST /users/me/subscription/trial — activate 14-day trial
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional, List

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes as sa_attrs

from core.database import get_db
from core.deps import get_current_user
from models.user import User
from models.company import Company

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/users", tags=["users"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class NotificationSettings(BaseModel):
    telegram: bool = True
    email: bool = False
    min_profit_for_notify: float = 200_000  # KZT — notify only above this profit


class FilterSettings(BaseModel):
    categories: List[str] = []          # ["product", "software_service"]
    keywords: List[str] = []            # ["принтер", "ноутбук", "мебель"]
    exclude_keywords: List[str] = []    # words to ignore
    platforms: List[str] = []           # ["goszakup", "zakupsk"]
    min_budget: Optional[float] = None  # KZT
    max_budget: Optional[float] = None  # KZT
    min_margin: Optional[float] = None  # percent (e.g. 30)
    regions: List[str] = []             # ["Алматы", "Астана"]


class UserSettingsRequest(BaseModel):
    filters: FilterSettings = FilterSettings()
    notifications: NotificationSettings = NotificationSettings()


class UserSettingsResponse(BaseModel):
    filters: FilterSettings
    notifications: NotificationSettings
    updated_at: Optional[datetime] = None


class SubscriptionResponse(BaseModel):
    plan: str                           # free | trial | pro | enterprise
    is_active: bool
    expires_at: Optional[datetime] = None
    days_left: Optional[int] = None
    trial_used: bool = False
    limits: dict
    features: List[str]


# ── Plan definitions ───────────────────────────────────────────────────────────

PLANS = {
    "free": {
        "limits": {
            "lots_per_day": 20,
            "ai_details": False,
            "bid_generator": False,
            "export": False,
        },
        "features": [
            "До 20 лотов в день",
            "Базовая аналитика прибыльности",
            "Поиск и фильтры",
        ],
    },
    "trial": {
        "limits": {
            "lots_per_day": -1,        # unlimited
            "ai_details": True,
            "bid_generator": True,
            "export": True,
        },
        "features": [
            "Безлимитные лоты (14 дней)",
            "Полная AI аналитика",
            "Генерация заявок",
            "Telegram уведомления",
            "Экспорт в Excel",
        ],
    },
    "pro": {
        "limits": {
            "lots_per_day": -1,
            "ai_details": True,
            "bid_generator": True,
            "export": True,
        },
        "features": [
            "Безлимитные лоты",
            "Полная AI аналитика",
            "Генерация заявок",
            "Telegram уведомления",
            "Экспорт в Excel",
            "Приоритетная поддержка",
        ],
    },
    "enterprise": {
        "limits": {
            "lots_per_day": -1,
            "ai_details": True,
            "bid_generator": True,
            "export": True,
        },
        "features": [
            "Всё из Pro",
            "Несколько пользователей",
            "API доступ",
            "Индивидуальные фильтры",
            "Персональный менеджер",
        ],
    },
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_plan_info(company: Company) -> dict:
    plan = company.subscription_plan or "free"
    settings_data = company.settings or {}
    expires_raw = settings_data.get("subscription_expires_at")

    expires_at: Optional[datetime] = None
    if expires_raw:
        try:
            expires_at = datetime.fromisoformat(expires_raw)
        except (ValueError, TypeError):
            pass

    now = datetime.now(timezone.utc)
    is_active = True
    days_left = None

    if plan in ("trial", "pro") and expires_at:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < now:
            plan = "free"
            is_active = True
        else:
            delta = expires_at - now
            days_left = delta.days

    plan_data = PLANS.get(plan, PLANS["free"])
    return {
        "plan": plan,
        "is_active": is_active,
        "expires_at": expires_at,
        "days_left": days_left,
        "trial_used": bool(settings_data.get("trial_used", False)),
        "limits": plan_data["limits"],
        "features": plan_data["features"],
    }


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/me/settings", response_model=UserSettingsResponse)
async def get_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return current user's filter and notification preferences."""
    result = await db.execute(
        select(Company).where(Company.id == current_user.company_id)
    )
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    raw = company.settings or {}
    filters_raw = raw.get("filters", {})
    notif_raw = raw.get("notifications", {})

    return UserSettingsResponse(
        filters=FilterSettings(**filters_raw) if filters_raw else FilterSettings(),
        notifications=NotificationSettings(**notif_raw) if notif_raw else NotificationSettings(),
        updated_at=company.updated_at,
    )


@router.put("/me/settings", response_model=UserSettingsResponse)
async def update_settings(
    body: UserSettingsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save user's filter and notification preferences."""
    result = await db.execute(
        select(Company).where(Company.id == current_user.company_id)
    )
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    existing = dict(company.settings or {})
    existing["filters"] = body.filters.model_dump()
    existing["notifications"] = body.notifications.model_dump()

    company.settings = dict(existing)          # new dict — forces SQLAlchemy to detect change
    sa_attrs.flag_modified(company, "settings")
    company.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(company)

    logger.info(
        "User settings updated",
        user_id=str(current_user.id),
        categories=body.filters.categories,
        keywords=len(body.filters.keywords),
    )

    return UserSettingsResponse(
        filters=body.filters,
        notifications=body.notifications,
        updated_at=company.updated_at,
    )


@router.get("/me/subscription", response_model=SubscriptionResponse)
async def get_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return subscription plan info for the current user's company."""
    result = await db.execute(
        select(Company).where(Company.id == current_user.company_id)
    )
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    info = _get_plan_info(company)
    return SubscriptionResponse(**info)


@router.post("/me/subscription/trial", response_model=SubscriptionResponse)
async def activate_trial(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Activate 14-day free trial (once per company)."""
    result = await db.execute(
        select(Company).where(Company.id == current_user.company_id)
    )
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    raw = company.settings or {}
    if raw.get("trial_used"):
        raise HTTPException(
            status_code=400,
            detail="Trial already used. Please upgrade to Pro to continue.",
        )

    expires_at = datetime.now(timezone.utc) + timedelta(days=14)
    raw["trial_used"] = True
    raw["subscription_expires_at"] = expires_at.isoformat()

    company.subscription_plan = "trial"
    company.settings = dict(raw)               # new dict — forces SQLAlchemy to detect change
    sa_attrs.flag_modified(company, "settings")
    company.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(company)

    logger.info("Trial activated", company_id=str(company.id))

    info = _get_plan_info(company)
    return SubscriptionResponse(**info)
