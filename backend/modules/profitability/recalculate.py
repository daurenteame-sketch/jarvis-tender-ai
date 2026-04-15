"""
Profitability Recalculation Service.

Recalculates profitability for all existing lots using:
  1. Category price catalog (KZ/RU/CN origin, real wholesale prices)
  2. Hash-based fallback (last resort, flags low confidence)

Cost model (mirrors engine.py):
  product_cost      — catalog price × qty (or hash ratio × budget)
  logistics_cost    — shipping by route: CN 12%, RU 6%, KZ 3%
  customs_cost      — import duty: CN 5%, RU 0%, KZ 0%
  broker_fee        — CN 1.5%, RU 0.5%, KZ 0%
  vat_amount        — 16% on (product + shipping + customs + broker)
  commission        — 5% of budget (bidding overhead)
  operational       — 3% of budget

  total_cost = sum above
  profit_margin = (budget - total_cost) / budget × 100
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

import structlog
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import async_session_factory
from core.config import settings
from models.tender_lot import TenderLot
from models.tender_lot_analysis import TenderLotAnalysis
from models.profitability import ProfitabilityAnalysis
from models.supplier import Supplier, SupplierMatch
from models.logistics import LogisticsEstimate
from modules.logistics.estimator import LOGISTICS_RATES
from modules.confidence.scorer import ConfidenceScorer
from modules.supplier.price_catalog import lookup_price
from modules.supplier.discovery import (
    _budget_ratio_fallback,
    _match_score,
    _build_url,
    _TEMPLATES,
    _infer_qty,
    _MIN_COST_RATIO,
)

logger = structlog.get_logger(__name__)
_scorer = ConfidenceScorer()

# ── Constants ─────────────────────────────────────────────────────────────────

_COMMISSION_RATE = 0.05   # 5% bidding overhead
_VAT_RATE        = 0.16   # 16% Kazakhstan VAT (use settings.VAT_RATE if available)
_BROKER_RATES    = {"CN": 0.015, "RU": 0.005, "KZ": 0.0}

# Service keywords — no physical import → no customs/logistics
_SERVICE_KEYWORDS = {
    "заправка картриджей", "заправка картриджа", "техническое обслуживание",
    "ремонтные работы", "ремонт здания", "уборка помещений", "охрана объекта",
    "транспортные услуги", "услуги перевозки", "услуги связи",
    "разработка программного", "сопровождение программного",
}


def _is_service(name: str) -> bool:
    nl = name.lower()
    return any(kw in nl for kw in _SERVICE_KEYWORDS) or nl.startswith("услуги")


# ── Brand detector — boosts spec_clarity when title has a known brand ──────────

_KNOWN_BRANDS = {
    # Electronics
    "hp", "hewlett", "canon", "epson", "brother", "kyocera", "ricoh", "xerox",
    "samsung", "lg", "panasonic", "sony", "philips", "toshiba",
    "dell", "lenovo", "asus", "acer", "apple", "macbook",
    "intel", "amd", "nvidia", "cisco", "huawei", "zte",
    "d-link", "tp-link", "mikrotik", "ubiquiti",
    # Industrial / electrical
    "abb", "siemens", "schneider", "legrand", "danfoss", "grundfos",
    "bosch", "makita", "dewalt", "stanley", "metabo",
    # Automotive
    "toyota", "ford", "chevrolet", "kia", "hyundai", "nissan", "mazda",
    "gaz", "ваз", "камаз", "урал", "зил", "lada",
    # Lubricants / chemicals
    "castrol", "mobil", "shell", "total", "liqui moly", "motul",
    # Office / printing
    "bic", "pilot", "stabilo", "dymo",
    # Furniture / household
    "ikea", "лдсп",
    # IT networking
    "linksys", "zyxel", "netgear",
}


def _detect_brand_in_name(product_name: str) -> bool:
    """Return True if product name contains a recognizable brand."""
    nl = product_name.lower()
    return any(brand in nl for brand in _KNOWN_BRANDS)


# ── Shared progress state ─────────────────────────────────────────────────────

@dataclass
class RecalcProgress:
    running: bool = False
    total: int = 0
    done: int = 0
    profitable: int = 0
    not_profitable: int = 0
    errors: int = 0
    finished: bool = False
    error_message: Optional[str] = None


_progress = RecalcProgress()


def get_progress() -> dict:
    return {
        "running":         _progress.running,
        "total":           _progress.total,
        "done":            _progress.done,
        "profitable":      _progress.profitable,
        "not_profitable":  _progress.not_profitable,
        "errors":          _progress.errors,
        "finished":        _progress.finished,
        "error_message":   _progress.error_message,
        "pct":             round(_progress.done / _progress.total * 100, 1) if _progress.total else 0,
    }


# ── Core math ─────────────────────────────────────────────────────────────────

def _compute(
    budget: float,
    product_name: str,
    quantity: Optional[float],
    spec_clarity: str,
    origin: str = "CN",
    price_source: str = "hash_fallback",
    catalog_confidence: int = 20,
) -> dict:
    """
    Full profitability calculation — no DB, no I/O.
    Uses correct VAT (16%), origin-dependent logistics, 5% commission.
    """
    vat_rate = getattr(settings, "VAT_RATE", _VAT_RATE)
    rates    = LOGISTICS_RATES.get(origin, LOGISTICS_RATES["CN"])
    qty      = quantity or 1.0

    # ── Price ────────────────────────────────────────────────────────────────
    if price_source == "catalog":
        # Try catalog first (pre-computed with correct qty)
        cat = lookup_price(product_name, budget=budget, quantity=qty)
        if cat:
            product_cost = cat["unit_price_kzt"] * qty
            origin       = cat["country"]
            rates        = LOGISTICS_RATES.get(origin, LOGISTICS_RATES["CN"])
        else:
            # Shouldn't happen, but fall back
            cost_ratio   = _budget_ratio_fallback(product_name)
            product_cost = budget * cost_ratio
            price_source = "hash_fallback"
            catalog_confidence = 20
    else:
        cost_ratio   = _budget_ratio_fallback(product_name)
        product_cost = budget * cost_ratio

    # Services: no import logistics
    if _is_service(product_name):
        origin = "KZ"
        rates  = LOGISTICS_RATES.get("KZ", LOGISTICS_RATES["CN"])

    # ── Cost breakdown ────────────────────────────────────────────────────────
    shipping_cost = product_cost * rates.get("shipping_rate", 0.03)
    customs_duty  = product_cost * rates.get("customs_duty_rate", 0.0)
    broker_fee    = product_cost * _BROKER_RATES.get(origin, 0.0)
    vat_base      = product_cost + shipping_cost + customs_duty + broker_fee
    vat_amount    = vat_base * vat_rate
    commission    = budget * _COMMISSION_RATE
    operational   = budget * (settings.OPERATIONAL_COST_PERCENT / 100)

    total_cost      = product_cost + shipping_cost + customs_duty + broker_fee + vat_amount + commission + operational
    expected_profit = budget - total_cost
    profit_margin   = (expected_profit / budget * 100) if budget > 0 else 0.0

    # Skip data-error lots (extreme negative margin = bad price estimate)
    if profit_margin < -200.0:
        profit_margin = -200.0
        expected_profit = budget * -2.0

    # Cap unrealistic margins
    if profit_margin > 80.0:
        profit_margin = 80.0
        expected_profit = budget * 0.80

    # Clamp to DB column Numeric(5,2) range [-999.99, 999.99]
    profit_margin = max(-999.99, min(999.99, profit_margin))
    is_profitable = profit_margin >= settings.MIN_PROFIT_MARGIN

    # ── Bid strategy ──────────────────────────────────────────────────────────
    recommended_bid = budget * 0.95
    safe_bid        = budget * 0.90
    aggressive_bid  = total_cost * 1.15

    # ── Risk ─────────────────────────────────────────────────────────────────
    s = 0
    if profit_margin < 10:   s += 3
    elif profit_margin < 20: s += 2
    elif profit_margin < 30: s += 1
    if spec_clarity == "vague":    s += 2
    elif spec_clarity == "partial": s += 1
    if origin == "CN":  s += 1
    if origin == "CN" and rates.get("lead_time_days", 30) > 30: s += 1
    risk_level = "high" if s >= 5 else ("medium" if s >= 3 else "low")

    # ── Confidence ────────────────────────────────────────────────────────────
    price_acc = {
        "catalog":       max(0.50, min(0.82, catalog_confidence / 100 * 1.10)),
        "hash_fallback": 0.20,
    }.get(price_source, 0.25)

    logistics_rel = {"KZ": 0.95, "RU": 0.85, "CN": 0.72}.get(origin, 0.65)

    if price_source == "catalog":
        # Use catalog confidence as match quality — more confidence = better supplier match
        match_base = max(0.55, min(0.92, catalog_confidence / 100))
        # Upgrade spec_clarity based on catalog confidence:
        #   conf≥75 → "clear" (known product category with accurate price)
        #   conf≥50 → "partial" (category found but not precise)
        if catalog_confidence >= 75:
            effective_clarity = "clear"
        elif catalog_confidence >= 50:
            effective_clarity = "partial"
        else:
            effective_clarity = spec_clarity  # keep original
    else:
        # hash_fallback: lower match score (no real supplier data)
        match_base = 0.42
        effective_clarity = spec_clarity

    # Further boost: if product_name contains a brand → spec at least "partial"
    _brand_detected = _detect_brand_in_name(product_name)
    if _brand_detected and effective_clarity == "vague":
        effective_clarity = "partial"
        match_base = max(match_base, 0.58)

    conf_score, conf_level = _scorer.score(
        spec_clarity=effective_clarity,
        supplier_match_score=match_base,
        logistics_reliability=logistics_rel,
        price_accuracy=price_acc,
    )

    # Flag suspicious: high margin with catalog/hash price and vague spec
    is_suspicious = (
        profit_margin > 40.0
        and price_source in ("hash_fallback", "catalog")
        and spec_clarity == "vague"
    )

    return {
        "product_cost":          round(product_cost, 2),
        "logistics_cost":        round(shipping_cost, 2),
        "customs_cost":          round(customs_duty, 2),
        "vat_amount":            round(vat_amount, 2),
        "operational_costs":     round(operational + commission, 2),
        "total_cost":            round(total_cost, 2),
        "expected_profit":       round(expected_profit, 2),
        "profit_margin_percent": round(profit_margin, 2),
        "is_profitable":         is_profitable,
        "confidence_level":      conf_level,
        "confidence_score":      round(conf_score, 2),
        "recommended_bid":       round(recommended_bid, 2),
        "safe_bid":              round(safe_bid, 2),
        "aggressive_bid":        round(aggressive_bid, 2),
        "risk_level":            risk_level,
        "origin_country":        origin,
        "_is_suspicious":        is_suspicious,
        "_price_source":         price_source,
    }


def _resolve_price_and_origin(
    product_name: str,
    budget: float,
    quantity: Optional[float],
) -> tuple[float, str, str, int, float]:
    """
    Returns (product_cost, origin, price_source, catalog_confidence, qty).
    Uses catalog first, then hash fallback.
    """
    qty = float(quantity) if quantity and quantity > 0 else 1.0

    # Try catalog with qty=1 first to get unit price
    cat_pre = lookup_price(product_name, budget=0, quantity=1)
    if cat_pre:
        unit_price = cat_pre["unit_price_kzt"]
        # Infer qty if needed
        if quantity is None or float(quantity) <= 1:
            if unit_price > 0 and budget > 0 and unit_price / budget < _MIN_COST_RATIO:
                inferred = _infer_qty(budget, unit_price)
                if inferred >= 2:
                    qty = inferred

        # Re-lookup with correct qty for accurate confidence
        cat = lookup_price(product_name, budget=budget, quantity=qty)
        if cat:
            product_cost = cat["unit_price_kzt"] * qty
            return product_cost, cat["country"], "catalog", cat["confidence"], qty

    # Hash fallback
    cost_ratio   = _budget_ratio_fallback(product_name)
    product_cost = budget * cost_ratio
    return product_cost, "CN", "hash_fallback", 20, qty


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _clear_old_records(session: AsyncSession, lot_id) -> None:
    await session.execute(
        delete(ProfitabilityAnalysis).where(ProfitabilityAnalysis.lot_id == lot_id)
    )
    sup_rows = await session.execute(
        select(SupplierMatch.id, SupplierMatch.supplier_id)
        .where(SupplierMatch.lot_id == lot_id)
    )
    rows = sup_rows.all()
    if rows:
        match_ids    = [r[0] for r in rows]
        supplier_ids = [r[1] for r in rows if r[1]]
        for mid in match_ids:
            await session.execute(delete(SupplierMatch).where(SupplierMatch.id == mid))
        for sid in supplier_ids:
            await session.execute(delete(Supplier).where(Supplier.id == sid))
    await session.execute(
        delete(LogisticsEstimate).where(LogisticsEstimate.lot_id == lot_id)
    )


async def _save_results(
    session: AsyncSession,
    lot: TenderLot,
    analysis: TenderLotAnalysis,
    result: dict,
    qty: float,
) -> None:
    product_name    = analysis.product_name or lot.title or "product"
    product_name_en = analysis.product_name_en or product_name
    base_unit_kzt   = result["product_cost"] / max(qty, 1.0)
    origin          = result["origin_country"]
    rates           = LOGISTICS_RATES.get(origin, LOGISTICS_RATES["CN"])

    for tpl in _TEMPLATES:
        unit_price_kzt = round(base_unit_kzt * tpl["price_factor"], 2)
        score = _match_score(product_name, tpl["match_base"])
        url   = _build_url(tpl["url_tpl"], product_name, product_name_en)

        supplier = Supplier(
            name=tpl["name"], country=tpl["country"], source=tpl["source"],
            contact_info={"note": "Recalculated estimate", "price_source": result.get("_price_source", "unknown")},
        )
        session.add(supplier)
        await session.flush()

        session.add(SupplierMatch(
            lot_id=lot.id, tender_id=lot.tender_id, supplier_id=supplier.id,
            product_name=product_name,
            unit_price=round(unit_price_kzt / settings.USD_TO_KZT, 4),
            currency="USD", unit_price_kzt=unit_price_kzt, moq=1,
            lead_time_days=tpl["lead_time"], match_score=score, source_url=url,
        ))

    session.add(LogisticsEstimate(
        lot_id=lot.id, tender_id=lot.tender_id,
        origin_country=origin,
        shipping_cost=result["logistics_cost"],
        customs_duty=result["customs_cost"],
        vat_amount=result["vat_amount"],
        total_logistics=result["logistics_cost"] + result["customs_cost"] + result["vat_amount"],
        lead_time_days=rates.get("lead_time_days", 30),
        route=rates.get("route", ""),
    ))

    # Strip internal key before saving
    clean = {k: v for k, v in result.items() if not k.startswith("_")}
    session.add(ProfitabilityAnalysis(
        lot_id=lot.id, tender_id=lot.tender_id, **clean,
    ))

    lot.is_profitable         = result["is_profitable"]
    lot.profit_margin_percent = result["profit_margin_percent"]
    lot.confidence_level      = result["confidence_level"]


# ── Main recalculation loop ───────────────────────────────────────────────────

BATCH_SIZE = 100


async def run_recalculation() -> None:
    """
    Recalculate profitability for all lots that have AI analysis.
    Uses catalog prices for known product categories; hash fallback otherwise.
    """
    global _progress
    _progress = RecalcProgress(running=True)

    try:
        async with async_session_factory() as session:
            q = (
                select(TenderLot)
                .join(TenderLotAnalysis, TenderLotAnalysis.lot_id == TenderLot.id)
                .where(TenderLot.category.notin_(["other"]))
                .where(TenderLot.category.isnot(None))
                .where(TenderLot.budget.isnot(None))
                .where(TenderLot.budget > 0)
            )
            all_lots = (await session.execute(q)).scalars().all()
            _progress.total = len(all_lots)

        # Apply SCAN_LIMIT only when > 0
        limit = settings.SCAN_LIMIT
        if limit > 0 and len(all_lots) > limit:
            logger.info("Recalculation capped by SCAN_LIMIT", original=len(all_lots), capped=limit)
            all_lots = all_lots[:limit]
            _progress.total = len(all_lots)

        logger.info("Recalculation started", total_lots=_progress.total)

        offset = 0
        while offset < _progress.total:
            batch = all_lots[offset: offset + BATCH_SIZE]
            for lot in batch:
                try:
                    await _recalculate_one(lot)
                    if lot.is_profitable:
                        _progress.profitable += 1
                    else:
                        _progress.not_profitable += 1
                except Exception as exc:
                    _progress.errors += 1
                    logger.error("Recalc error", lot_id=str(lot.id)[:8], error=str(exc)[:120])
                finally:
                    _progress.done += 1

            offset += BATCH_SIZE
            await asyncio.sleep(0)

        _progress.finished = True
        logger.info(
            "Recalculation finished",
            total=_progress.total,
            profitable=_progress.profitable,
            not_profitable=_progress.not_profitable,
            errors=_progress.errors,
        )

    except Exception as exc:
        _progress.error_message = str(exc)
        logger.error("Recalculation failed", error=str(exc))
    finally:
        _progress.running = False


async def _recalculate_one(lot: TenderLot) -> None:
    async with async_session_factory() as session:
        lot_row = await session.execute(
            select(TenderLot).where(TenderLot.id == lot.id)
        )
        lot_fresh = lot_row.scalar_one_or_none()
        if not lot_fresh:
            return

        analysis_row = await session.execute(
            select(TenderLotAnalysis).where(TenderLotAnalysis.lot_id == lot.id)
        )
        analysis = analysis_row.scalar_one_or_none()
        if not analysis:
            return

        product_name = analysis.product_name or lot_fresh.title or "product"
        raw_qty = (
            float(analysis.quantity_extracted) if analysis.quantity_extracted
            else float(lot_fresh.quantity) if lot_fresh.quantity
            else None
        )
        spec_clarity = analysis.spec_clarity or "vague"
        budget       = float(lot_fresh.budget)

        # Resolve price + origin via catalog
        product_cost, origin, price_source, cat_conf, qty = _resolve_price_and_origin(
            product_name=product_name,
            budget=budget,
            quantity=raw_qty,
        )

        result = _compute(
            budget=budget,
            product_name=product_name,
            quantity=qty,
            spec_clarity=spec_clarity,
            origin=origin,
            price_source=price_source,
            catalog_confidence=cat_conf,
        )

        # Override product_cost with what _resolve_price_and_origin computed
        # (since _compute re-computes internally; ensure consistency)
        result["product_cost"] = round(product_cost, 2)

        await _clear_old_records(session, lot_fresh.id)
        await _save_results(session, lot_fresh, analysis, result, qty)
        await session.commit()

        lot.is_profitable         = result["is_profitable"]
        lot.profit_margin_percent = result["profit_margin_percent"]

        logger.debug(
            "Recalculated",
            lot=product_name[:40],
            margin=f"{result['profit_margin_percent']:.1f}%",
            origin=origin,
            src=price_source,
            conf=f"{result['confidence_level']}({result['confidence_score']})",
        )
