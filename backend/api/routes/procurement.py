"""
Procurement Plan and Purchase History routes.

/procurement/plan    — upcoming tenders/lots grouped by month and category
/procurement/history — completed procurement: closed lots with details
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, desc, and_, or_, extract
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.deps import get_current_user
from models.user import User
from models.tender import Tender
from models.tender_lot import TenderLot

router = APIRouter(prefix="/procurement", tags=["procurement"])

# ── helpers ───────────────────────────────────────────────────────────────────

_CATEGORY_LABELS = {
    "product":          "Товары / Оборудование",
    "software_service": "IT / ПО",
    "other":            "Прочие услуги",
    "unknown":          "Не определено",
}

_METHOD_LABELS = {
    "open_tender":   "Открытый тендер",
    "single_source": "Из одного источника",
    "price_offers":  "Ценовые предложения",
    "open_contest":  "Открытый конкурс",
    "short_list":    "Короткий список",
}

_MONTH_RU = [
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]

PLATFORM_LABELS = {
    "goszakup": "GosZakup",
    "zakupsk":  "Zakup SK",
}


def _fmt_month(year: int, month: int) -> str:
    return f"{_MONTH_RU[month]} {year}"


# ── Plan endpoints ─────────────────────────────────────────────────────────────

@router.get("/plan")
async def get_procurement_plan(
    year: Optional[int] = Query(None, description="Filter by year (default: current year)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upcoming procurement plan — lots with future deadlines grouped by month and category.
    Shows what tenders are expected in the coming months.
    """
    now = datetime.now(timezone.utc)
    plan_year = year or now.year

    # Window: from start of plan_year to end of plan_year
    from_dt = datetime(plan_year, 1, 1, tzinfo=timezone.utc)
    to_dt   = datetime(plan_year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

    # --- Monthly totals (lots with deadline in the window) ---
    month_expr = extract("month", TenderLot.deadline_at)
    monthly_q = await db.execute(
        select(
            month_expr.label("month"),
            TenderLot.category,
            func.count(TenderLot.id).label("lot_count"),
            func.sum(TenderLot.budget).label("total_budget"),
        )
        .where(
            and_(
                TenderLot.deadline_at >= from_dt,
                TenderLot.deadline_at <= to_dt,
                TenderLot.budget > 0,
            )
        )
        .group_by(month_expr, TenderLot.category)
        .order_by(month_expr)
    )
    monthly_rows = monthly_q.all()

    # --- Aggregate into month → categories structure ---
    months_map: dict[int, dict] = {}
    for row in monthly_rows:
        m = int(row.month)
        if m not in months_map:
            months_map[m] = {
                "month":       m,
                "month_label": _fmt_month(plan_year, m),
                "categories":  [],
                "total_budget": 0.0,
                "total_lots":   0,
                "is_past":      m < now.month and plan_year <= now.year,
            }
        cat_key = row.category or "unknown"
        budget  = float(row.total_budget or 0)
        months_map[m]["categories"].append({
            "category":       cat_key,
            "category_label": _CATEGORY_LABELS.get(cat_key, cat_key),
            "lot_count":      int(row.lot_count),
            "total_budget":   budget,
        })
        months_map[m]["total_budget"] += budget
        months_map[m]["total_lots"]   += int(row.lot_count)

    # Round budgets
    for m_data in months_map.values():
        m_data["total_budget"] = round(m_data["total_budget"], 2)
        for cat in m_data["categories"]:
            cat["total_budget"] = round(cat["total_budget"], 2)

    # Sort by month
    months = sorted(months_map.values(), key=lambda x: x["month"])

    # --- Year summary ---
    total_budget_year = sum(m["total_budget"] for m in months)
    total_lots_year   = sum(m["total_lots"] for m in months)

    # --- Top upcoming customers (next 3 months) ---
    horizon = now + timedelta(days=90)
    top_customers_q = await db.execute(
        select(
            Tender.customer_name,
            Tender.customer_region,
            Tender.platform,
            func.count(TenderLot.id).label("lot_count"),
            func.sum(TenderLot.budget).label("total_budget"),
        )
        .join(TenderLot, TenderLot.tender_id == Tender.id)
        .where(
            and_(
                TenderLot.deadline_at >= now,
                TenderLot.deadline_at <= horizon,
                TenderLot.budget > 0,
                Tender.customer_name.isnot(None),
            )
        )
        .group_by(Tender.customer_name, Tender.customer_region, Tender.platform)
        .order_by(desc("total_budget"))
        .limit(10)
    )
    top_customers = [
        {
            "customer_name":   r.customer_name,
            "customer_region": r.customer_region,
            "platform":        PLATFORM_LABELS.get(r.platform, r.platform),
            "lot_count":       int(r.lot_count),
            "total_budget":    round(float(r.total_budget or 0), 2),
        }
        for r in top_customers_q.all()
    ]

    # --- Category breakdown for the year ---
    cat_budget_expr = func.sum(TenderLot.budget).label("total_budget")
    cat_q = await db.execute(
        select(
            TenderLot.category,
            func.count(TenderLot.id).label("lot_count"),
            cat_budget_expr,
        )
        .where(
            and_(
                TenderLot.deadline_at >= from_dt,
                TenderLot.deadline_at <= to_dt,
                TenderLot.budget > 0,
            )
        )
        .group_by(TenderLot.category)
        .order_by(desc(cat_budget_expr))
    )
    categories = [
        {
            "category":       r.category or "unknown",
            "category_label": _CATEGORY_LABELS.get(r.category or "unknown", r.category or "unknown"),
            "lot_count":      int(r.lot_count),
            "total_budget":   round(float(r.total_budget or 0), 2),
        }
        for r in cat_q.all()
    ]

    # --- Available years ---
    yr2_expr = extract("year", TenderLot.deadline_at)
    years_q = await db.execute(
        select(yr2_expr.label("yr"))
        .where(TenderLot.deadline_at.isnot(None))
        .group_by(yr2_expr)
        .order_by(desc(yr2_expr))
        .limit(5)
    )
    available_years = [int(r.yr) for r in years_q.all() if r.yr]

    return {
        "year":            plan_year,
        "available_years": available_years,
        "summary": {
            "total_lots":   total_lots_year,
            "total_budget": round(total_budget_year, 2),
            "months_with_data": len(months),
        },
        "months":          months,
        "top_customers":   top_customers,
        "categories":      categories,
    }


# ── History endpoints ──────────────────────────────────────────────────────────

@router.get("/history")
async def get_procurement_history(
    page:     int            = Query(1, ge=1),
    per_page: int            = Query(25, ge=1, le=100),
    search:   Optional[str]  = Query(None),
    platform: Optional[str]  = Query(None),
    category: Optional[str]  = Query(None),
    year:     Optional[int]  = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Purchase history — completed/closed procurement lots.
    Shows past tenders: customer, category, budget, method, date closed.
    """
    now = datetime.now(timezone.utc)

    # Base filter: closed tenders OR lots with past deadline
    conditions = [
        or_(
            Tender.status.in_(["closed", "finished", "completed", "cancelled"]),
            and_(
                TenderLot.deadline_at < now,
                TenderLot.deadline_at.isnot(None),
            )
        )
    ]

    if search:
        term = f"%{search}%"
        conditions.append(
            or_(
                TenderLot.title.ilike(term),
                Tender.customer_name.ilike(term),
                Tender.customer_region.ilike(term),
            )
        )
    if platform:
        conditions.append(TenderLot.platform == platform)
    if category:
        conditions.append(TenderLot.category == category)
    if year:
        conditions.append(extract("year", TenderLot.deadline_at) == year)

    base_q = (
        select(TenderLot, Tender)
        .join(Tender, Tender.id == TenderLot.tender_id)
        .where(and_(*conditions))
    )

    # Total count
    count_q = await db.execute(
        select(func.count()).select_from(
            select(TenderLot.id)
            .join(Tender, Tender.id == TenderLot.tender_id)
            .where(and_(*conditions))
            .subquery()
        )
    )
    total = count_q.scalar() or 0

    # Paginated results
    offset = (page - 1) * per_page
    rows = await db.execute(
        base_q
        .order_by(desc(TenderLot.deadline_at))
        .limit(per_page)
        .offset(offset)
    )
    results = rows.all()

    items = []
    for lot, tender in results:
        # Try to extract winner info from raw_data if available
        raw = lot.raw_data or {}
        winner_name = raw.get("winnerName") or raw.get("winner_name")
        winner_bin  = raw.get("winnerBin")  or raw.get("winner_bin")
        contract_sum = raw.get("contractSum") or raw.get("contract_sum")

        items.append({
            "id":                  str(lot.id),
            "tender_id":           str(tender.id),
            "platform":            PLATFORM_LABELS.get(lot.platform, lot.platform),
            "platform_key":        lot.platform,
            "tender_external_id":  tender.external_id,
            "lot_external_id":     lot.lot_external_id,
            "title":               lot.title,
            "category":            lot.category or "unknown",
            "category_label":      _CATEGORY_LABELS.get(lot.category or "unknown", lot.category or "unknown"),
            "budget":              float(lot.budget) if lot.budget else None,
            "currency":            lot.currency or "KZT",
            "customer_name":       tender.customer_name,
            "customer_region":     tender.customer_region,
            "procurement_method":  _METHOD_LABELS.get(tender.procurement_method or "", tender.procurement_method or ""),
            "deadline_at":         lot.deadline_at.isoformat() if lot.deadline_at else None,
            "published_at":        tender.published_at.isoformat() if tender.published_at else None,
            "status":              tender.status,
            # Profitability info (if was analyzed)
            "is_profitable":       lot.is_profitable,
            "profit_margin_percent": float(lot.profit_margin_percent) if lot.profit_margin_percent else None,
            # Winner info (from raw data if available)
            "winner_name":         winner_name,
            "winner_bin":          winner_bin,
            "contract_sum":        float(contract_sum) if contract_sum else None,
        })

    # --- Stats for filters sidebar ---
    # Year distribution
    yr_expr = extract("year", TenderLot.deadline_at)
    years_q = await db.execute(
        select(
            yr_expr.label("yr"),
            func.count(TenderLot.id).label("cnt"),
        )
        .join(Tender, Tender.id == TenderLot.tender_id)
        .where(
            and_(
                TenderLot.deadline_at.isnot(None),
                or_(
                    Tender.status.in_(["closed", "finished", "completed", "cancelled"]),
                    TenderLot.deadline_at < now,
                )
            )
        )
        .group_by(yr_expr)
        .order_by(desc(yr_expr))
        .limit(5)
    )
    year_counts = [{"year": int(r.yr), "count": int(r.cnt)} for r in years_q.all() if r.yr]

    return {
        "items":   items,
        "total":   total,
        "page":    page,
        "per_page": per_page,
        "pages":   max(1, -(-total // per_page)),  # ceiling div
        "year_counts": year_counts,
    }


@router.get("/history/stats")
async def get_history_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Quick summary stats for the history page header.
    """
    now = datetime.now(timezone.utc)
    three_years_ago = now - timedelta(days=3 * 365)

    past_condition = and_(
        TenderLot.deadline_at < now,
        TenderLot.deadline_at >= three_years_ago,
        TenderLot.budget > 0,
    )

    total_q = await db.execute(
        select(func.count(TenderLot.id)).where(past_condition)
    )
    total_lots = total_q.scalar() or 0

    budget_q = await db.execute(
        select(func.sum(TenderLot.budget)).where(past_condition)
    )
    total_budget = float(budget_q.scalar() or 0)

    customer_q = await db.execute(
        select(func.count(func.distinct(Tender.customer_bin)))
        .join(TenderLot, TenderLot.tender_id == Tender.id)
        .where(past_condition)
    )
    unique_customers = customer_q.scalar() or 0

    # Category breakdown
    budget_sum_expr = func.sum(TenderLot.budget).label("budget_sum")
    cat_q = await db.execute(
        select(
            TenderLot.category,
            func.count(TenderLot.id).label("cnt"),
            budget_sum_expr,
        )
        .where(past_condition)
        .group_by(TenderLot.category)
        .order_by(desc(budget_sum_expr))
        .limit(5)
    )
    top_categories = [
        {
            "category":       r.category or "unknown",
            "category_label": _CATEGORY_LABELS.get(r.category or "unknown", r.category or "unknown"),
            "count":          int(r.cnt),
            "total_budget":   round(float(r.budget_sum or 0), 2),
        }
        for r in cat_q.all()
    ]

    # Top customers by volume
    cust_budget_expr = func.sum(TenderLot.budget).label("total_budget")
    top_cust_q = await db.execute(
        select(
            Tender.customer_name,
            Tender.customer_region,
            func.count(TenderLot.id).label("lot_count"),
            cust_budget_expr,
        )
        .join(TenderLot, TenderLot.tender_id == Tender.id)
        .where(and_(past_condition, Tender.customer_name.isnot(None)))
        .group_by(Tender.customer_name, Tender.customer_region)
        .order_by(desc(cust_budget_expr))
        .limit(10)
    )
    top_customers = [
        {
            "customer_name":   r.customer_name,
            "customer_region": r.customer_region,
            "lot_count":       int(r.lot_count),
            "total_budget":    round(float(r.total_budget or 0), 2),
        }
        for r in top_cust_q.all()
    ]

    return {
        "total_lots":       total_lots,
        "total_budget":     round(total_budget, 2),
        "unique_customers": unique_customers,
        "top_categories":   top_categories,
        "top_customers":    top_customers,
        "period":           "3 года",
    }
