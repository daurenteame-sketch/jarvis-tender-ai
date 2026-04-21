"""
Suppliers API routes.

GET /suppliers/search?q=...    — product marketplace search (KZ/RU/CN links)
GET /suppliers/recent          — recently found suppliers from analyzed lots
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.deps import get_current_user
from models.user import User
from models.supplier import SupplierMatch, Supplier
from models.tender_lot import TenderLot
from modules.supplier.product_search import get_product_links

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.get("/search")
async def search_product_marketplaces(
    q: str = Query(..., min_length=2, max_length=200, description="Product name to search"),
    current_user: User = Depends(get_current_user),
):
    """
    Search for a product across KZ/RU/CN marketplaces.
    Returns 6-8 links: real product pages where available, search pages otherwise.
    """
    links = await get_product_links(
        product_name=q,
        characteristics={},
        product_name_en="",
        max_links=8,
    )
    return {
        "query": q,
        "links": links,
        "count": len(links),
    }


@router.get("/recent")
async def get_recent_suppliers(
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns recently analyzed supplier matches with product names and prices.
    """
    rows = await db.execute(
        select(SupplierMatch, Supplier, TenderLot)
        .join(Supplier, SupplierMatch.supplier_id == Supplier.id)
        .outerjoin(TenderLot, SupplierMatch.lot_id == TenderLot.id)
        .order_by(desc(SupplierMatch.created_at))
        .limit(limit)
    )
    results = []
    seen_products: set[str] = set()

    for sm, s, lot in rows.all():
        product_key = f"{sm.product_name or ''}:{s.name}"
        if product_key in seen_products:
            continue
        seen_products.add(product_key)

        results.append({
            "product_name":    sm.product_name or (lot.title if lot else ""),
            "supplier_name":   s.name,
            "country":         s.country,
            "source":          s.source,
            "unit_price_kzt":  float(sm.unit_price_kzt) if sm.unit_price_kzt else None,
            "lead_time_days":  sm.lead_time_days,
            "match_score":     float(sm.match_score) if sm.match_score else None,
            "source_url":      sm.source_url,
            "lot_id":          str(sm.lot_id) if sm.lot_id else None,
            "lot_title":       lot.title if lot else None,
        })

    return {"items": results, "total": len(results)}
