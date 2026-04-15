"""
Profitability Engine — realistic margin calculation.

Cost breakdown (all in KZT):
  product_cost      — cheapest supplier × quantity
  logistics_cost    — shipping by route (CN 12%, RU 6%, KZ 3%)
  customs_cost      — import duty + broker fees
  vat_amount        — 16% on (product + shipping + customs)
  commission        — bidding overhead: bank guarantee, goszakup fee = 5%
  operational_costs — overhead: 3% of budget

  total_cost = sum above
  expected_profit = budget - total_cost
  profit_margin = expected_profit / budget × 100

Sanity guards:
  • product_cost < 8% budget → quantity likely missing → force low confidence
  • margin > 80% → unrealistic → clamp + force low confidence
  • margin < -200% → data error → skip
  • Services (no physical good) → set origin=KZ automatically
"""
from __future__ import annotations

import uuid
from typing import Optional
import structlog
from sqlalchemy import select

from core.config import settings
from core.database import async_session_factory
from models.profitability import ProfitabilityAnalysis
from models.tender_lot import TenderLot
from modules.supplier.discovery import SupplierDiscoveryEngine, _budget_ratio_fallback
from modules.logistics.estimator import LogisticsEstimator
from modules.confidence.scorer import ConfidenceScorer

logger = structlog.get_logger(__name__)

_COMMISSION_RATE    = 0.05   # 5% bidding overhead
_MIN_COST_RATIO     = 0.08   # product_cost / budget sanity floor
_MAX_REALISTIC_MARGIN = 80.0  # clamp anything above

# Service keywords → no physical import → origin=KZ, no customs
_SERVICE_KEYWORDS = {
    "заправка картриджей", "заправка картриджа",
    "техническое обслуживание", "технического обслуживания",
    "ремонтные работы", "ремонт здания", "уборка помещений",
    "охрана объекта", "охранная деятельность",
    "транспортные услуги", "услуги перевозки",
    "услуги связи", "интернет", "телефония",
    "разработка программного", "сопровождение программного",
}


def _is_service(product_name: str) -> bool:
    pl = product_name.lower()
    return any(kw in pl for kw in _SERVICE_KEYWORDS) or pl.startswith("услуги")


class ProfitabilityEngine:
    def __init__(self):
        self.supplier_engine = SupplierDiscoveryEngine()
        self.logistics_estimator = LogisticsEstimator()
        self.confidence_scorer = ConfidenceScorer()

    async def analyze(
        self,
        budget: float,
        analysis: dict,
        spec_text: str = "",
        lot_title: str = "",
        lot_id: Optional[uuid.UUID] = None,
        tender_id: Optional[uuid.UUID] = None,
    ) -> Optional[dict]:

        if not budget or budget <= 0:
            return None

        technical_params = analysis.get("technical_params", {})
        quantity         = analysis.get("quantity") or analysis.get("quantity_extracted")
        spec_clarity     = analysis.get("spec_clarity", "vague")

        # Resolve product identity
        from modules.product_resolver import resolve_product
        resolved = resolve_product(
            spec_text=spec_text, title=lot_title,
            ai_product_name=analysis.get("product_name") or "",
            ai_brand_model=analysis.get("brand_model") or "",
            ai_technical_params=technical_params,
        )
        search_query    = resolved["search_query"]
        product_name_en = analysis.get("product_name_en") or resolved["product_name"]

        # Supplier discovery
        suppliers = await self.supplier_engine.find_suppliers(
            product_name=search_query,
            technical_params=technical_params,
            quantity=quantity,
            budget_kzt=budget,
            lot_id=lot_id,
            tender_id=tender_id,
            product_name_en=product_name_en,
            key_requirements=analysis.get("key_requirements") or [],
            spec_clarity=spec_clarity,
        )

        if not suppliers:
            return None

        best = min(suppliers, key=lambda s: s["total_product_cost_kzt"])
        product_cost    = best["total_product_cost_kzt"]
        price_source    = best.get("price_source", "unknown")
        price_conf      = best.get("price_confidence", 0)

        # Determine best origin: services → KZ, else use catalog/AI recommendation
        if _is_service(search_query):
            origin_country = "KZ"
        else:
            # Use best_origin from discovery (catalog or AI picked it)
            origin_country = best.get("best_origin", best.get("country", "CN"))

        custom_duty = best.get("customs_duty_rate")

        # ── Sanity: product cost floor ────────────────────────────────────────
        forced_low = False
        if product_cost < budget * _MIN_COST_RATIO:
            old = product_cost
            ratio = _budget_ratio_fallback(search_query)
            product_cost = budget * ratio
            forced_low = True
            print(f"[engine] SANITY: cost {old:,.0f} < 8% budget "
                  f"→ override to {product_cost:,.0f} KZT (ratio={ratio:.2f})", flush=True)

        # Logistics
        logistics = await self.logistics_estimator.estimate(
            product_cost_kzt=product_cost,
            origin_country=origin_country,
            custom_duty_rate=custom_duty,
            lot_id=lot_id,
            tender_id=tender_id,
        )

        # Full cost breakdown
        logistics_cost    = logistics["shipping_cost"]
        customs_cost      = logistics["customs_duty"]
        vat_amount        = logistics["vat_amount"]
        operational_costs = budget * (settings.OPERATIONAL_COST_PERCENT / 100)
        commission        = budget * _COMMISSION_RATE

        total_cost      = product_cost + logistics_cost + customs_cost + vat_amount + operational_costs + commission
        expected_profit = budget - total_cost
        profit_margin   = (expected_profit / budget * 100) if budget > 0 else 0.0
        is_profitable   = profit_margin >= settings.MIN_PROFIT_MARGIN

        # ── Sanity: data-error guard ──────────────────────────────────────────
        if profit_margin < -200.0:
            logger.warning("Margin too negative, skipping", margin=f"{profit_margin:.1f}%")
            return None

        # ── Sanity: margin cap ────────────────────────────────────────────────
        if profit_margin > _MAX_REALISTIC_MARGIN:
            logger.warning(
                "Margin capped",
                margin_before=f"{profit_margin:.1f}%",
                cap=f"{_MAX_REALISTIC_MARGIN}%",
                price_source=price_source,
            )
            profit_margin = _MAX_REALISTIC_MARGIN
            expected_profit = budget * (profit_margin / 100)
            forced_low = True

        # Flag suspicious: margin > 40% with low-quality pricing and vague spec
        is_suspicious = (
            profit_margin > 40.0
            and price_source in ("hash_fallback", "catalog")
            and spec_clarity == "vague"
        )

        # Bid strategy
        recommended_bid = budget * 0.95
        safe_bid        = budget * 0.90
        aggressive_bid  = total_cost * 1.15

        # Risk
        risk_level = self._assess_risk(profit_margin, spec_clarity, origin_country,
                                       logistics.get("lead_time_days", 30))

        # Confidence — exact_match boosts price_accuracy significantly
        exact_match = best.get("exact_match", False)

        _web_acc = min(0.92, price_conf / 100) if exact_match else min(0.72, price_conf / 100)
        # catalog: confidence from lookup_price (48-88) → accuracy 0.50-0.82
        _cat_acc = max(0.50, min(0.82, price_conf / 100 * 1.10))
        price_accuracy = {
            "web_kz":        _web_acc,        # KZ local price — most reliable
            "web_ru":        _web_acc * 0.95, # RU price
            "web_china":     _web_acc * 0.92, # CN price
            "ai_estimate":   0.62 if exact_match else 0.52,
            "catalog":       _cat_acc,         # keyword-matched catalog
            "hash_fallback": 0.20,
        }.get(price_source, 0.25)

        # Effective spec_clarity: upgrade when we have a precise price signal
        effective_clarity = spec_clarity
        if exact_match and price_source.startswith("web_") and spec_clarity == "vague":
            # Web search found exact product — spec is effectively "partial"
            effective_clarity = "partial"
        elif price_source == "catalog":
            # Catalog match: use confidence to determine clarity
            if price_conf >= 75:
                effective_clarity = "clear"
            elif price_conf >= 50:
                effective_clarity = "partial" if spec_clarity == "vague" else spec_clarity

        # Use catalog_confidence directly as supplier_match when available
        if price_source == "catalog" and price_conf >= 50:
            supplier_match = max(0.55, min(0.92, price_conf / 100))
        else:
            supplier_match = best.get("match_score", 0.5)

        conf_score, conf_level = self.confidence_scorer.score(
            spec_clarity=effective_clarity,
            supplier_match_score=supplier_match,
            logistics_reliability={"KZ": 0.95, "RU": 0.85, "CN": 0.72}.get(origin_country, 0.65),
            price_accuracy=price_accuracy,
        )

        if forced_low or is_suspicious:
            conf_level  = "low"
            conf_score  = min(conf_score, 0.35)

        # Accuracy percent for UI
        accuracy_pct = round(conf_score * 100, 1)

        # Collect supplier links from best supplier
        supplier_links: list = best.get("supplier_links", [])

        # Persist
        await self._save_analysis(
            lot_id=lot_id, tender_id=tender_id,
            product_cost=product_cost, logistics_cost=logistics_cost,
            customs_cost=customs_cost, vat_amount=vat_amount,
            operational_costs=operational_costs + commission,
            total_cost=total_cost, expected_profit=expected_profit,
            profit_margin=profit_margin, is_profitable=is_profitable,
            confidence_level=conf_level, confidence_score=conf_score,
            recommended_bid=recommended_bid, safe_bid=safe_bid,
            aggressive_bid=aggressive_bid, risk_level=risk_level,
            origin_country=origin_country,
        )
        if lot_id:
            await self._update_lot(lot_id, is_profitable, profit_margin, conf_level)

        logger.info(
            "Profitability calculated",
            lot_id=str(lot_id)[:8] if lot_id else None,
            product=search_query[:50],
            origin=origin_country,
            margin=f"{profit_margin:.1f}%",
            product_cost=f"{product_cost:,.0f}",
            total_cost=f"{total_cost:,.0f}",
            budget=f"{budget:,.0f}",
            price_source=price_source,
            exact_match=exact_match,
            confidence=conf_level,
            accuracy_pct=accuracy_pct,
            suspicious=is_suspicious,
        )

        return {
            "lot_id":                str(lot_id) if lot_id else None,
            "tender_id":             str(tender_id) if tender_id else None,
            "budget":                budget,
            "product_cost":          round(product_cost, 2),
            "logistics_cost":        round(logistics_cost, 2),
            "customs_cost":          round(customs_cost, 2),
            "vat_amount":            round(vat_amount, 2),
            "operational_costs":     round(operational_costs, 2),
            "commission":            round(commission, 2),
            "total_cost":            round(total_cost, 2),
            "expected_profit":       round(expected_profit, 2),
            "profit_margin_percent": round(profit_margin, 2),
            "is_profitable":         is_profitable,
            "is_suspicious":         is_suspicious,
            "confidence_level":      conf_level,
            "confidence_score":      round(conf_score, 2),
            "accuracy_pct":          accuracy_pct,
            "recommended_bid":       round(recommended_bid, 2),
            "safe_bid":              round(safe_bid, 2),
            "aggressive_bid":        round(aggressive_bid, 2),
            "risk_level":            risk_level,
            "origin_country":        origin_country,
            "lead_time_days":        logistics.get("lead_time_days", 30),
            "route":                 logistics.get("route", ""),
            "supplier_name":         best.get("supplier_name"),
            "alibaba_url":           best.get("alibaba_url"),
            "price_source":          price_source,
            "price_confidence":      price_conf,
            "exact_match":           exact_match,
            "supplier_links":        supplier_links[:5],
        }

    async def _save_analysis(self, lot_id, tender_id, product_cost, logistics_cost,
                              customs_cost, vat_amount, operational_costs, total_cost,
                              expected_profit, profit_margin, is_profitable,
                              confidence_level, confidence_score, recommended_bid,
                              safe_bid, aggressive_bid, risk_level, origin_country):
        async with async_session_factory() as session:
            session.add(ProfitabilityAnalysis(
                lot_id=lot_id, tender_id=tender_id,
                product_cost=round(product_cost, 2),
                logistics_cost=round(logistics_cost, 2),
                customs_cost=round(customs_cost, 2),
                vat_amount=round(vat_amount, 2),
                operational_costs=round(operational_costs, 2),
                total_cost=round(total_cost, 2),
                expected_profit=round(expected_profit, 2),
                profit_margin_percent=round(profit_margin, 2),
                is_profitable=is_profitable,
                confidence_level=confidence_level,
                confidence_score=round(confidence_score, 2),
                recommended_bid=round(recommended_bid, 2),
                safe_bid=round(safe_bid, 2),
                aggressive_bid=round(aggressive_bid, 2),
                risk_level=risk_level,
                origin_country=origin_country,
            ))
            await session.commit()

    async def _update_lot(self, lot_id, is_profitable, margin, conf_level):
        async with async_session_factory() as session:
            r = await session.execute(select(TenderLot).where(TenderLot.id == lot_id))
            lot = r.scalar_one_or_none()
            if lot:
                lot.is_profitable = is_profitable
                lot.profit_margin_percent = round(margin, 2)
                lot.confidence_level = conf_level
                await session.commit()

    def _assess_risk(self, margin, spec_clarity, country, lead_time):
        s = 0
        # Margin risk: scaled to realistic 15-40% range
        if margin < 10:   s += 4   # barely breaking even
        elif margin < 17: s += 3   # below minimum viable
        elif margin < 25: s += 2   # thin margin
        elif margin < 35: s += 1   # acceptable
        # Spec clarity risk
        if spec_clarity == "vague":    s += 2
        elif spec_clarity == "partial": s += 1
        # Origin risk
        if country == "CN":                   s += 1
        if country == "CN" and lead_time > 30: s += 1
        return "high" if s >= 5 else ("medium" if s >= 3 else "low")
