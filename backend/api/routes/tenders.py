"""
Tender API routes.
"""
from typing import Optional
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, desc
import io

from core.database import get_db
from core.deps import get_current_user
from models.user import User
from models.tender import Tender
from models.tender_lot import TenderLot
from models.profitability import ProfitabilityAnalysis
from models.analysis import TenderAnalysis
from models.logistics import LogisticsEstimate
from models.supplier import SupplierMatch, Supplier
from api.schemas import TenderListItem, TenderDetail, TenderFilter, UserActionCreate
from modules.bid_generator.generator import BidProposalGenerator
from modules.self_learning.learning import SelfLearningSystem

router = APIRouter(prefix="/tenders", tags=["tenders"])
bid_generator = BidProposalGenerator()
learning_system = SelfLearningSystem()


@router.get("", response_model=dict)
async def list_tenders(
    platform: Optional[str] = None,
    category: Optional[str] = None,
    is_profitable: Optional[bool] = None,
    confidence_level: Optional[str] = None,
    min_budget: Optional[float] = None,
    max_budget: Optional[float] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List tenders with filters and pagination."""
    query = (
        select(Tender, ProfitabilityAnalysis)
        .outerjoin(ProfitabilityAnalysis, Tender.id == ProfitabilityAnalysis.tender_id)
        .order_by(desc(Tender.first_seen_at))
    )

    conditions = []
    if platform:
        conditions.append(Tender.platform == platform)
    if category:
        conditions.append(Tender.category == category)
    if is_profitable is not None:
        conditions.append(ProfitabilityAnalysis.is_profitable == is_profitable)
    if confidence_level:
        conditions.append(ProfitabilityAnalysis.confidence_level == confidence_level)
    if min_budget:
        conditions.append(Tender.budget >= min_budget)
    if max_budget:
        conditions.append(Tender.budget <= max_budget)
    if search:
        conditions.append(
            or_(
                Tender.title.ilike(f"%{search}%"),
                Tender.description.ilike(f"%{search}%"),
            )
        )

    if conditions:
        query = query.where(and_(*conditions))

    # Total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Paginated results
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)
    result = await db.execute(query)
    rows = result.all()

    items = []
    for tender, prof in rows:
        item = {
            "id": str(tender.id),
            "platform": tender.platform,
            "external_id": tender.external_id,
            "title": tender.title,
            "category": tender.category,
            "budget": float(tender.budget) if tender.budget else None,
            "currency": tender.currency,
            "status": tender.status,
            "customer_name": tender.customer_name,
            "published_at": tender.published_at.isoformat() if tender.published_at else None,
            "deadline_at": tender.deadline_at.isoformat() if tender.deadline_at else None,
            "first_seen_at": tender.first_seen_at.isoformat() if tender.first_seen_at else None,
            "is_profitable": prof.is_profitable if prof else None,
            "profit_margin": float(prof.profit_margin_percent) if prof and prof.profit_margin_percent else None,
            "confidence_level": prof.confidence_level if prof else None,
            "expected_profit": float(prof.expected_profit) if prof and prof.expected_profit else None,
        }
        items.append(item)

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


@router.get("/{tender_id}")
async def get_tender(
    tender_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get full tender details with analysis."""
    result = await db.execute(select(Tender).where(Tender.id == tender_id))
    tender = result.scalar_one_or_none()

    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")

    # Fetch related data
    analysis_result = await db.execute(
        select(TenderAnalysis).where(TenderAnalysis.tender_id == tender_id)
    )
    analysis = analysis_result.scalar_one_or_none()

    prof_result = await db.execute(
        select(ProfitabilityAnalysis).where(ProfitabilityAnalysis.tender_id == tender_id)
    )
    profitability = prof_result.scalar_one_or_none()

    logistics_result = await db.execute(
        select(LogisticsEstimate).where(LogisticsEstimate.tender_id == tender_id)
    )
    logistics = logistics_result.scalar_one_or_none()

    suppliers_result = await db.execute(
        select(SupplierMatch, Supplier)
        .outerjoin(Supplier, SupplierMatch.supplier_id == Supplier.id)
        .where(SupplierMatch.tender_id == tender_id)
    )
    supplier_data = [
        {
            "supplier_name": s.name if s else None,
            "country": s.country if s else None,
            "unit_price_kzt": float(sm.unit_price_kzt) if sm.unit_price_kzt else None,
            "lead_time_days": sm.lead_time_days,
            "match_score": float(sm.match_score) if sm.match_score else None,
            "source_url": sm.source_url,
        }
        for sm, s in suppliers_result.all()
    ]

    # Fetch lots (summary list)
    lots_result = await db.execute(
        select(TenderLot)
        .where(TenderLot.tender_id == tender_id)
        .order_by(TenderLot.first_seen_at)
    )
    lots_data = [
        {
            "id": str(lot.id),
            "lot_external_id": lot.lot_external_id,
            "title": lot.title,
            "budget": float(lot.budget) if lot.budget else None,
            "quantity": float(lot.quantity) if lot.quantity else None,
            "unit": lot.unit,
            "category": lot.category,
            "is_profitable": lot.is_profitable,
            "profit_margin_percent": float(lot.profit_margin_percent) if lot.profit_margin_percent else None,
            "confidence_level": lot.confidence_level,
            "is_analyzed": lot.is_analyzed,
        }
        for lot in lots_result.scalars().all()
    ]

    return {
        "id": str(tender.id),
        "platform": tender.platform,
        "external_id": tender.external_id,
        "title": tender.title,
        "description": tender.description,
        "category": tender.category,
        "budget": float(tender.budget) if tender.budget else None,
        "currency": tender.currency,
        "status": tender.status,
        "customer_name": tender.customer_name,
        "customer_bin": tender.customer_bin,
        "published_at": tender.published_at.isoformat() if tender.published_at else None,
        "deadline_at": tender.deadline_at.isoformat() if tender.deadline_at else None,
        "first_seen_at": tender.first_seen_at.isoformat() if tender.first_seen_at else None,
        "documents": tender.documents,
        "lots": lots_data,
        "analysis": {
            "product_name": analysis.product_name,
            "brand_model": analysis.brand_model,
            "dimensions": analysis.dimensions,
            "technical_params": analysis.technical_params,
            "quantity": float(analysis.quantity) if analysis.quantity else None,
            "unit": analysis.unit,
            "analogs_allowed": analysis.analogs_allowed,
            "spec_clarity": analysis.spec_clarity,
            "ai_summary": analysis.ai_summary,
        } if analysis else None,
        "profitability": {
            "product_cost": float(profitability.product_cost) if profitability.product_cost else None,
            "logistics_cost": float(profitability.logistics_cost) if profitability.logistics_cost else None,
            "customs_cost": float(profitability.customs_cost) if profitability.customs_cost else None,
            "vat_amount": float(profitability.vat_amount) if profitability.vat_amount else None,
            "operational_costs": float(profitability.operational_costs) if profitability.operational_costs else None,
            "total_cost": float(profitability.total_cost) if profitability.total_cost else None,
            "expected_profit": float(profitability.expected_profit) if profitability.expected_profit else None,
            "profit_margin_percent": float(profitability.profit_margin_percent) if profitability.profit_margin_percent else None,
            "is_profitable": profitability.is_profitable,
            "confidence_level": profitability.confidence_level,
            "confidence_score": float(profitability.confidence_score) if profitability.confidence_score else None,
            "recommended_bid": float(profitability.recommended_bid) if profitability.recommended_bid else None,
            "safe_bid": float(profitability.safe_bid) if profitability.safe_bid else None,
            "aggressive_bid": float(profitability.aggressive_bid) if profitability.aggressive_bid else None,
            "risk_level": profitability.risk_level,
        } if profitability else None,
        "logistics": {
            "origin_country": logistics.origin_country,
            "shipping_cost": float(logistics.shipping_cost) if logistics.shipping_cost else None,
            "customs_duty": float(logistics.customs_duty) if logistics.customs_duty else None,
            "vat_amount": float(logistics.vat_amount) if logistics.vat_amount else None,
            "total_logistics": float(logistics.total_logistics) if logistics.total_logistics else None,
            "lead_time_days": logistics.lead_time_days,
            "route": logistics.route,
        } if logistics else None,
        "suppliers": supplier_data,
    }


@router.get("/{tender_id}/bid")
async def generate_bid(
    tender_id: uuid.UUID,
    company_name: str = Query("Ваша компания"),
    company_bin: str = Query(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate DOCX bid proposal for a tender."""
    result = await db.execute(select(Tender).where(Tender.id == tender_id))
    tender = result.scalar_one_or_none()

    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")

    analysis_result = await db.execute(
        select(TenderAnalysis).where(TenderAnalysis.tender_id == tender_id)
    )
    analysis = analysis_result.scalar_one_or_none()

    prof_result = await db.execute(
        select(ProfitabilityAnalysis).where(ProfitabilityAnalysis.tender_id == tender_id)
    )
    profitability = prof_result.scalar_one_or_none()

    tender_dict = {
        "title": tender.title,
        "budget": float(tender.budget) if tender.budget else 0,
        "deadline_at": tender.deadline_at.isoformat() if tender.deadline_at else None,
        "customer_name": tender.customer_name,
    }
    analysis_dict = analysis.extracted_specs if analysis else {}
    prof_dict = {}
    if profitability:
        prof_dict = {
            "total_cost": float(profitability.total_cost) if profitability.total_cost else 0,
            "expected_profit": float(profitability.expected_profit) if profitability.expected_profit else 0,
            "profit_margin_percent": float(profitability.profit_margin_percent) if profitability.profit_margin_percent else 0,
            "recommended_bid": float(profitability.recommended_bid) if profitability.recommended_bid else 0,
            "lead_time_days": 30,
            "origin_country": "CN",
        }

    docx_bytes = await bid_generator.generate(
        tender_data=tender_dict,
        analysis=analysis_dict,
        profitability=prof_dict,
        company_name=company_name,
        company_bin=company_bin,
    )

    filename = f"bid_{tender.external_id}.docx"
    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{tender_id}/action")
async def record_action(
    tender_id: uuid.UUID,
    action_data: UserActionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Record user action on a tender."""
    valid_actions = {"viewed", "ignored", "bid_submitted", "won", "lost"}
    if action_data.action not in valid_actions:
        raise HTTPException(status_code=400, detail=f"Invalid action. Must be one of: {valid_actions}")

    action = await learning_system.record_action(
        tender_id=tender_id,
        user_id=current_user.id,
        action=action_data.action,
        actual_bid_amount=action_data.actual_bid_amount,
        notes=action_data.notes,
    )
    return {"id": str(action.id), "action": action.action, "status": "recorded"}
