"""
Analytics API routes — dashboard stats and trends.
"""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from core.database import get_db
from core.deps import get_current_user
from models.user import User
from models.tender import Tender
from models.tender_lot import TenderLot
from models.profitability import ProfitabilityAnalysis
from models.scan_run import ScanRun
from modules.self_learning.learning import SelfLearningSystem

router = APIRouter(prefix="/analytics", tags=["analytics"])
learning = SelfLearningSystem()


@router.get("/summary")
async def get_dashboard_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get dashboard summary statistics."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Total tenders scanned
    total_result = await db.execute(select(func.count(Tender.id)))
    total_tenders = total_result.scalar()

    # Total lots
    total_lots_result = await db.execute(select(func.count(TenderLot.id)))
    total_lots = total_lots_result.scalar()

    # Profitable lots (stamped directly on TenderLot)
    profitable_result = await db.execute(
        select(func.count(TenderLot.id)).where(TenderLot.is_profitable == True)
    )
    profitable_lots = profitable_result.scalar()

    # High-confidence profitable lots
    high_conf_result = await db.execute(
        select(func.count(TenderLot.id))
        .where(TenderLot.is_profitable == True)
        .where(TenderLot.confidence_level == "high")
    )
    high_confidence = high_conf_result.scalar()

    # Average margin across profitable lots
    avg_margin_result = await db.execute(
        select(func.avg(TenderLot.profit_margin_percent))
        .where(TenderLot.is_profitable == True)
    )
    avg_margin = float(avg_margin_result.scalar() or 0)

    # Total budget in all lots scanned
    budget_result = await db.execute(select(func.sum(TenderLot.budget)))
    total_budget = float(budget_result.scalar() or 0)

    # Last completed scan
    last_scan_result = await db.execute(
        select(ScanRun.completed_at)
        .where(ScanRun.status == "completed")
        .order_by(desc(ScanRun.completed_at))
        .limit(1)
    )
    last_scan = last_scan_result.scalar()

    # Lots discovered today
    today_lots_result = await db.execute(
        select(func.count(TenderLot.id)).where(TenderLot.first_seen_at >= today_start)
    )
    lots_today = today_lots_result.scalar()

    # Profitable lots found today
    today_profitable_result = await db.execute(
        select(func.count(TenderLot.id))
        .where(TenderLot.first_seen_at >= today_start)
        .where(TenderLot.is_profitable == True)
    )
    profitable_today = today_profitable_result.scalar()

    return {
        "total_tenders": total_tenders,
        "total_lots": total_lots,
        # Both names: frontend uses profitable_tenders, keep profitable_lots for API compat
        "profitable_tenders": profitable_lots,
        "profitable_lots": profitable_lots,
        "high_confidence": high_confidence,
        "avg_margin": round(avg_margin, 1),
        "total_budget_scanned": round(total_budget),
        "last_scan_at": last_scan.isoformat() if last_scan else None,
        # Both names: frontend uses tenders_today
        "tenders_today": lots_today,
        "lots_today": lots_today,
        "profitable_today": profitable_today,
    }


@router.get("/trends")
async def get_profit_trends(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get profitability trends over time."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    result = await db.execute(
        select(
            func.date(TenderLot.first_seen_at).label("date"),
            func.count(TenderLot.id).label("lots_found"),
            func.count(TenderLot.id).filter(
                TenderLot.is_profitable == True
            ).label("profitable_found"),
            func.avg(TenderLot.profit_margin_percent).filter(
                TenderLot.is_profitable == True
            ).label("avg_margin"),
        )
        .where(TenderLot.first_seen_at >= since)
        .group_by(func.date(TenderLot.first_seen_at))
        .order_by(func.date(TenderLot.first_seen_at))
    )

    return [
        {
            "date": str(row.date),
            # Both names: frontend chart uses tenders_found
            "tenders_found": row.lots_found,
            "lots_found": row.lots_found,
            "profitable_found": row.profitable_found or 0,
            "avg_margin": round(float(row.avg_margin or 0), 1),
        }
        for row in result.all()
    ]


@router.get("/top-categories")
async def get_top_categories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get most profitable tender categories."""
    result = await db.execute(
        select(
            TenderLot.category,
            func.count(TenderLot.id).label("count"),
            func.avg(TenderLot.profit_margin_percent).label("avg_margin"),
            func.sum(TenderLot.budget).label("total_budget"),
        )
        .where(TenderLot.is_profitable == True)
        .group_by(TenderLot.category)
        .order_by(desc(func.count(TenderLot.id)))
    )

    return [
        {
            "category": row.category or "unknown",
            "count": row.count,
            "avg_margin": round(float(row.avg_margin or 0), 1),
            "total_budget": round(float(row.total_budget or 0)),
        }
        for row in result.all()
    ]


@router.get("/scan-history")
async def get_scan_history(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get recent scan run history."""
    result = await db.execute(
        select(ScanRun)
        .order_by(desc(ScanRun.started_at))
        .limit(limit)
    )
    runs = result.scalars().all()

    return [
        {
            "id": str(run.id),
            "platform": run.platform,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "tenders_found": run.tenders_found,
            "tenders_new": run.tenders_new,
            "profitable_found": run.profitable_found,
            "status": run.status,
            "error_message": run.error_message,
        }
        for run in runs
    ]


@router.get("/margin-distribution")
async def get_margin_distribution(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return count of profitable lots bucketed by margin range.
    Useful for a histogram on the analytics page.
    """
    result = await db.execute(
        select(TenderLot.profit_margin_percent)
        .where(TenderLot.is_profitable == True)
        .where(TenderLot.profit_margin_percent.isnot(None))
    )
    margins = [float(row[0]) for row in result.all()]

    buckets = [
        {"range": "50–60%", "min": 50, "max": 60, "count": 0},
        {"range": "60–70%", "min": 60, "max": 70, "count": 0},
        {"range": "70–80%", "min": 70, "max": 80, "count": 0},
        {"range": "80–90%", "min": 80, "max": 90, "count": 0},
        {"range": "90%+",   "min": 90, "max": 999, "count": 0},
    ]
    for m in margins:
        for b in buckets:
            if b["min"] <= m < b["max"]:
                b["count"] += 1
                break

    return [{"range": b["range"], "count": b["count"]} for b in buckets]


@router.get("/platform-breakdown")
async def get_platform_breakdown(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return per-platform stats: total lots, profitable lots, avg margin.
    """
    result = await db.execute(
        select(
            TenderLot.platform,
            func.count(TenderLot.id).label("total"),
            func.count(TenderLot.id).filter(TenderLot.is_profitable == True).label("profitable"),
            func.avg(TenderLot.profit_margin_percent).filter(
                TenderLot.is_profitable == True
            ).label("avg_margin"),
            func.sum(TenderLot.budget).label("total_budget"),
        )
        .group_by(TenderLot.platform)
        .order_by(desc(func.count(TenderLot.id)))
    )

    return [
        {
            "platform": row.platform or "unknown",
            "total_lots": row.total,
            "profitable_lots": row.profitable,
            "avg_margin": round(float(row.avg_margin or 0), 1),
            "total_budget": round(float(row.total_budget or 0)),
        }
        for row in result.all()
    ]


@router.get("/learning-stats")
async def get_learning_stats(current_user: User = Depends(get_current_user)):
    """Get self-learning system statistics."""
    return await learning.get_learning_stats()


@router.get("/category-profitability")
async def get_category_profitability(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Per-category profitability stats: total lots, profitable %, avg margin, total budget.
    """
    result = await db.execute(
        select(
            TenderLot.category,
            func.count(TenderLot.id).label("total"),
            func.count(TenderLot.id).filter(TenderLot.is_profitable == True).label("profitable"),  # noqa
            func.count(TenderLot.id).filter(TenderLot.confidence_level == "high").label("high_conf"),
            func.avg(TenderLot.profit_margin_percent).filter(
                TenderLot.is_profitable == True  # noqa
            ).label("avg_margin"),
            func.sum(TenderLot.budget).label("total_budget"),
        )
        .where(TenderLot.category.isnot(None))
        .group_by(TenderLot.category)
        .order_by(desc(func.count(TenderLot.id)))
    )

    rows = result.all()
    return [
        {
            "category": row.category,
            "total_lots": row.total,
            "profitable_lots": row.profitable,
            "high_confidence_lots": row.high_conf,
            "profitable_pct": round(row.profitable / row.total * 100, 1) if row.total else 0,
            "avg_margin": round(float(row.avg_margin or 0), 1),
            "total_budget": round(float(row.total_budget or 0)),
        }
        for row in rows
    ]


@router.get("/confidence-breakdown")
async def get_confidence_breakdown(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Confidence level distribution with avg margin per level."""
    result = await db.execute(
        select(
            TenderLot.confidence_level,
            func.count(TenderLot.id).label("total"),
            func.avg(TenderLot.profit_margin_percent).label("avg_margin"),
            func.sum(TenderLot.budget).label("total_budget"),
        )
        .where(TenderLot.is_analyzed == True)  # noqa
        .group_by(TenderLot.confidence_level)
        .order_by(desc(func.count(TenderLot.id)))
    )
    total_all = 0
    rows = result.all()
    for r in rows:
        total_all += r.total

    order = {"high": 0, "medium": 1, "low": 2, None: 3}
    rows_sorted = sorted(rows, key=lambda r: order.get(r.confidence_level, 9))

    return [
        {
            "confidence_level": row.confidence_level or "unknown",
            "total": row.total,
            "pct": round(row.total / total_all * 100, 1) if total_all else 0,
            "avg_margin": round(float(row.avg_margin or 0), 1),
            "total_budget_mln": round(float(row.total_budget or 0) / 1_000_000, 1),
        }
        for row in rows_sorted
    ]
