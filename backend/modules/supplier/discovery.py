"""
Supplier Discovery Engine.

Price resolution chain (best → fallback):
  1. Web search (gpt-4o-search-preview)        → real market prices, structured JSON
     1a. kz_kzt  → origin=KZ (no customs)
     1b. ru_kzt  → origin=RU (Russia)
     1c. china_usd → origin=CN
  2. AI training-data estimate (gpt-4o)        → knowledge-based prices
     Prefers KZ/RU for food, construction, office; CN for electronics
  3. Category catalog lookup                   → hardcoded realistic ranges
  4. Budget-ratio hash fallback               → last resort (flags low confidence)

Confidence model:
  exact_match=True  + web  → overall_conf = min(web_conf, 90)   (≈ 75-90%)
  exact_match=False + web  → overall_conf = min(web_conf * 0.7, 65) (≈ 45-65%)
  ai_estimate              → overall_conf = 55
  catalog                  → overall_conf = catalog["confidence"]
  hash_fallback            → overall_conf = 20

Returns 3 price-estimate rows (Alibaba, 1688, Kaspi) PLUS a `marketplace_links`
field with 4-8 real/search product page URLs across KZ/RU/CN platforms.
"""
from __future__ import annotations

import asyncio
import hashlib
import urllib.parse
import uuid
from functools import lru_cache
from typing import Optional
import structlog

from core.database import async_session_factory
from core.config import settings
from models.supplier import Supplier, SupplierMatch
from modules.supplier.price_catalog import lookup_price
from modules.supplier.product_search import get_product_links

logger = structlog.get_logger(__name__)

# ── Supplier templates ─────────────────────────────────────────────────────────

_TEMPLATES = [
    {
        "name":         "Alibaba.com",
        "country":      "CN",
        "source":       "alibaba",
        "price_factor": 1.00,
        "lead_time":    30,
        "match_base":   0.80,
        "duty_rate":    settings.CUSTOMS_DUTY_CHINA,
        "url_tpl":      "https://www.alibaba.com/trade/search?SearchText={q_en}",
    },
    {
        "name":         "1688.com",
        "country":      "CN",
        "source":       "1688",
        "price_factor": 0.82,
        "lead_time":    37,
        "match_base":   0.72,
        "duty_rate":    settings.CUSTOMS_DUTY_CHINA,
        "url_tpl":      "https://s.1688.com/selloffer/offer_search.htm?keywords={q_en}",
    },
    {
        "name":         "Kaspi Магазин",
        "country":      "KZ",
        "source":       "kaspi",
        "price_factor": 1.40,
        "lead_time":    7,
        "match_base":   0.62,
        "duty_rate":    0.0,
        "url_tpl":      "https://kaspi.kz/shop/search/?text={q_ru}",
    },
]

# Minimum cost-ratio (product_cost / budget). Below this → suspicious.
_MIN_COST_RATIO = 0.08

# Russian rouble to KZT (approximate 2024-2025)
_RUB_TO_KZT = 5.2

# Simple in-process cache for web search results (avoids duplicate OpenAI calls
# for the same product within a single batch run).
_WEB_SEARCH_CACHE: dict[str, dict] = {}
_WEB_CACHE_MAX = 200  # max entries; evict oldest when full


def _cache_key(product_name: str, characteristics: str) -> str:
    raw = f"{product_name.lower().strip()}|{characteristics[:200]}"
    return hashlib.md5(raw.encode()).hexdigest()


def _budget_ratio_fallback(product_name: str) -> float:
    """
    Last-resort cost ratio relative to budget.
    Returns what fraction of budget should be product cost.
    Range: [0.38, 0.72] — chosen to give margins of 28-62%.
    """
    name_lower = product_name.lower()
    h = int(hashlib.md5(name_lower.encode()).hexdigest()[:8], 16)
    seed = h % 10_000

    electronics = {"ноутбук", "laptop", "компьютер", "монитор", "принтер",
                   "мфу", "проектор", "роутер", "сервер", "планшет"}
    heavy = {"кондиционер", "холодильник", "котел", "генератор", "экскаватор",
             "насос", "компрессор", "трансформатор"}

    if any(kw in name_lower for kw in electronics):
        return 0.62 + seed / 10_000 * 0.18   # [0.62, 0.80]
    if any(kw in name_lower for kw in heavy):
        return 0.55 + seed / 10_000 * 0.20   # [0.55, 0.75]
    return 0.38 + seed / 10_000 * 0.22       # [0.38, 0.60]


def _match_score(product_name: str, base: float, confidence: int = 50) -> float:
    h = int(hashlib.md5((product_name + "ms").encode()).hexdigest()[:4], 16)
    delta = (h % 100) / 1000
    raw = base - 0.05 + delta
    adj = raw * (confidence / 100) ** 0.3
    return round(max(0.20, min(0.98, adj)), 2)


def _build_url(tpl: str, name_ru: str, name_en: str) -> str:
    q_en = urllib.parse.quote_plus((name_en or name_ru)[:80])
    q_ru = urllib.parse.quote_plus(name_ru[:80])
    return tpl.format(q_en=q_en, q_ru=q_ru)


def _infer_qty(budget: float, unit_kzt: float) -> float:
    """Infer quantity when spec didn't have it: budget × 0.60 / unit_price."""
    if unit_kzt <= 0 or budget <= 0:
        return 1.0
    implied = (budget * 0.60) / unit_kzt
    return float(min(max(round(implied), 2), 500_000))


# ── Main class ─────────────────────────────────────────────────────────────────

class SupplierDiscoveryEngine:

    async def find_suppliers(
        self,
        product_name: str,
        technical_params: dict,
        quantity: Optional[float] = None,
        budget_kzt: float = 0,
        lot_id: Optional[uuid.UUID] = None,
        tender_id: Optional[uuid.UUID] = None,
        product_name_en: str = "",
        key_requirements: Optional[list] = None,
        spec_clarity: str = "vague",
    ) -> list[dict]:

        if not product_name:
            product_name = "product"

        explicit_qty = quantity is not None and float(quantity) > 0
        qty = float(quantity) if explicit_qty else 1.0
        budget = float(budget_kzt) if budget_kzt > 0 else 1.0

        # ── Resolution chain ──────────────────────────────────────────────────
        base_kzt: Optional[float] = None
        origin_country: str = "CN"
        price_source: str = "none"
        web_identified_model: Optional[str] = None
        web_citations: list = []
        supplier_links: list[str] = []
        catalog_confidence: int = 0
        web_confidence = 0
        exact_match = False

        # Start real marketplace product link search in background (non-blocking)
        marketplace_links_task = asyncio.create_task(
            get_product_links(
                product_name=product_name,
                characteristics=technical_params,
                product_name_en=product_name_en,
                max_links=8,
            )
        )

        # Step 1: Web search (with in-process cache)
        if settings.OPENAI_API_KEY:
            try:
                from integrations.openai_client.client import OpenAIClient
                _ai = OpenAIClient()
                chars = ", ".join(f"{k}: {v}" for k, v in (technical_params or {}).items())[:300]
                _ck = _cache_key(product_name, chars)
                if _ck in _WEB_SEARCH_CACHE:
                    web = _WEB_SEARCH_CACHE[_ck]
                    print(f"[discovery] WEB cache hit: {product_name[:40]!r}", flush=True)
                else:
                    web = await asyncio.wait_for(
                        _ai.search_product_web(
                            product_name=product_name,
                            characteristics=chars,
                            quantity=qty,
                        ),
                        timeout=30.0,
                    )
                    if web:
                        if len(_WEB_SEARCH_CACHE) >= _WEB_CACHE_MAX:
                            # evict oldest entry
                            _WEB_SEARCH_CACHE.pop(next(iter(_WEB_SEARCH_CACHE)))
                        _WEB_SEARCH_CACHE[_ck] = web
                if web:
                    web_identified_model = web.get("identified_model")
                    web_citations        = web.get("citations", [])
                    supplier_links       = web.get("supplier_links", [])
                    web_confidence       = web.get("confidence", 0)
                    exact_match          = bool(web.get("exact_match", False))

                    kz_kzt    = web.get("kz_kzt")
                    ru_kzt    = web.get("ru_kzt")
                    china_usd = web.get("china_usd")

                    if kz_kzt and kz_kzt > 0:
                        # Kazakhstan market — best: no customs, local delivery
                        base_kzt = float(kz_kzt)
                        origin_country = "KZ"
                        price_source = "web_kz"
                        print(f"[discovery] WEB kz: {kz_kzt:,.0f} ₸/unit "
                              f"exact={exact_match} conf={web_confidence}", flush=True)

                    elif ru_kzt and ru_kzt > 0:
                        # Russian market price (already in KZT from AI)
                        base_kzt = float(ru_kzt)
                        origin_country = "RU"
                        price_source = "web_ru"
                        print(f"[discovery] WEB ru: {ru_kzt:,.0f} ₸/unit "
                              f"exact={exact_match} conf={web_confidence}", flush=True)

                    elif china_usd and china_usd > 0:
                        base_kzt = float(china_usd) * settings.USD_TO_KZT
                        origin_country = "CN"
                        price_source = "web_china"
                        print(f"[discovery] WEB cn: ${china_usd:.2f}/unit → {base_kzt:,.0f} ₸ "
                              f"model={web_identified_model!r} exact={exact_match} "
                              f"conf={web_confidence}", flush=True)

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Web search failed", error=str(exc)[:120])

        # Step 2: AI training-data estimate
        if not base_kzt and settings.OPENAI_API_KEY:
            try:
                from integrations.openai_client.client import OpenAIClient
                _ai = OpenAIClient()
                ai_res = await asyncio.wait_for(
                    _ai.search_suppliers_ai(
                        product_name=product_name,
                        technical_params=technical_params,
                        quantity=qty,
                        key_requirements=key_requirements,
                        spec_clarity=spec_clarity,
                    ),
                    timeout=25.0,
                )

                best_src = ai_res.get("best_source_country", "CN")
                origin_country = best_src if best_src in ("CN", "RU", "KZ") else "CN"

                # Try KZ price first
                kz_price_kzt = ((ai_res.get("estimated_unit_price_kzt") or {}).get("kazakhstan") or 0)
                ru_price_kzt = ((ai_res.get("estimated_unit_price_kzt") or {}).get("russia") or 0)
                china_likely = float(
                    ((ai_res.get("estimated_unit_price_usd") or {})
                     .get("china") or {})
                    .get("likely") or 0
                )

                if origin_country == "KZ" and kz_price_kzt > 0:
                    base_kzt = float(kz_price_kzt)
                    price_source = "ai_estimate"
                    print(f"[discovery] AI kz: {base_kzt:,.0f} ₸/unit src=KZ", flush=True)

                elif origin_country == "RU" and ru_price_kzt > 0:
                    base_kzt = float(ru_price_kzt)
                    price_source = "ai_estimate"
                    print(f"[discovery] AI ru: {base_kzt:,.0f} ₸/unit src=RU", flush=True)

                elif china_likely > 0:
                    base_kzt = china_likely * settings.USD_TO_KZT
                    price_source = "ai_estimate"
                    print(f"[discovery] AI cn: ${china_likely:.2f}/unit → {base_kzt:,.0f} ₸ "
                          f"src={origin_country}", flush=True)

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("AI estimate failed", error=str(exc)[:120])

        # Step 3: Category catalog lookup
        # First pass: lookup with qty=1 to get unit price, then infer qty if needed,
        # then re-lookup with real qty for accurate confidence.
        if not base_kzt:
            cat_pre = lookup_price(product_name, budget=0, quantity=1)  # skip sanity check
            if cat_pre:
                _unit = cat_pre["unit_price_kzt"]
                # Quick qty inference using catalog unit price
                if not explicit_qty and _unit > 0 and budget > 0:
                    if _unit / budget < _MIN_COST_RATIO:
                        _inferred = _infer_qty(budget, _unit)
                        if _inferred >= 2:
                            qty = _inferred
                            print(f"[discovery] CATALOG QTY infer: unit={_unit:,.0f} ₸ "
                                  f"→ qty={qty:.0f}", flush=True)
                # Now lookup with accurate qty for correct confidence
                cat = lookup_price(product_name, budget=budget, quantity=qty)
                if cat:
                    base_kzt = cat["unit_price_kzt"]
                    origin_country = cat["country"]
                    catalog_confidence = cat["confidence"]
                    price_source = "catalog"
                    print(f"[discovery] CATALOG: '{cat['match_keyword']}' → "
                          f"{base_kzt:,.0f} ₸/unit origin={origin_country} "
                          f"conf={catalog_confidence} qty={qty:.0f}", flush=True)

        # Step 4: Budget-ratio hash fallback
        if not base_kzt or base_kzt <= 0:
            ratio = _budget_ratio_fallback(product_name)
            base_kzt = (budget * ratio) / max(qty, 1.0)
            price_source = "hash_fallback"
            print(f"[discovery] HASH fallback: ratio={ratio:.2f} → "
                  f"{base_kzt:,.0f} ₸/unit (budget={budget:,.0f})", flush=True)

        # ── Quantity inference (for web/AI steps that didn't infer yet) ───────
        if not explicit_qty and base_kzt > 0 and budget > 0:
            if base_kzt / budget < _MIN_COST_RATIO:
                inferred = _infer_qty(budget, base_kzt)
                if inferred >= 2:
                    print(f"[discovery] QTY infer: unit={base_kzt:,.0f} ₸, "
                          f"budget={budget:,.0f} → qty={inferred:.0f}", flush=True)
                    qty = inferred

        # ── Sanity: total cost must be ≤ 92% of budget ───────────────────────
        cheapest_total = base_kzt * _TEMPLATES[1]["price_factor"] * qty
        if cheapest_total > budget * 0.92 and budget > 0:
            scale = (budget * 0.68) / max(cheapest_total, 1.0)
            old = base_kzt
            base_kzt *= scale
            print(f"[discovery] CLAMP: total {cheapest_total:,.0f} > 92% budget "
                  f"→ scaled {old:,.0f}→{base_kzt:,.0f} ₸/unit", flush=True)

        # ── Confidence calculation ────────────────────────────────────────────
        if price_source == "web_kz":
            if exact_match:
                overall_conf = min(web_confidence, 90)    # ~75-90%
            else:
                overall_conf = min(int(web_confidence * 0.75), 68)

        elif price_source == "web_ru":
            if exact_match:
                overall_conf = min(web_confidence, 85)
            else:
                overall_conf = min(int(web_confidence * 0.70), 62)

        elif price_source == "web_china":
            if exact_match:
                overall_conf = min(web_confidence, 88)
            else:
                overall_conf = min(int(web_confidence * 0.70), 65)

        elif price_source == "ai_estimate":
            overall_conf = 55

        elif price_source == "catalog":
            overall_conf = catalog_confidence

        else:  # hash_fallback
            overall_conf = 20

        # ── Collect marketplace links (real product pages + search URLs) ────────
        marketplace_links: list[dict] = []
        try:
            marketplace_links = await asyncio.wait_for(marketplace_links_task, timeout=9.0)
        except (asyncio.TimeoutError, Exception) as exc:
            logger.warning("Marketplace links task failed", error=str(exc)[:80])
            try:
                marketplace_links_task.cancel()
            except Exception:
                pass

        # ── Build 3 supplier results ─────────────────────────────────────────
        search_name = web_identified_model or product_name
        name_en = web_identified_model or product_name_en or product_name

        results: list[dict] = []
        for tpl in _TEMPLATES:
            unit_kzt  = round(base_kzt * tpl["price_factor"], 2)
            total_kzt = round(unit_kzt * qty, 2)
            score     = _match_score(product_name, tpl["match_base"], overall_conf)
            url       = _build_url(tpl["url_tpl"], search_name, name_en)

            if lot_id:
                try:
                    await _save_supplier_match(
                        lot_id=lot_id, tender_id=tender_id,
                        name=tpl["name"], country=tpl["country"],
                        source=tpl["source"], product_name=search_name,
                        unit_price_kzt=unit_kzt, lead_time=tpl["lead_time"],
                        match_score=score, source_url=url,
                    )
                except Exception as exc:
                    logger.warning("DB save failed", supplier=tpl["name"], error=str(exc)[:80])

            results.append({
                "supplier_name":          tpl["name"],
                "country":                tpl["country"],
                "unit_price_kzt":         unit_kzt,
                "unit_price_usd":         round(unit_kzt / settings.USD_TO_KZT, 2),
                "total_product_cost_kzt": total_kzt,
                "inferred_quantity":      qty,
                "lead_time_days":         tpl["lead_time"],
                "match_score":            score,
                "customs_duty_rate":      tpl["duty_rate"],
                "price_source":           price_source,
                "price_confidence":       overall_conf,
                "exact_match":            exact_match,
                "is_estimate":            price_source in ("hash_fallback", "catalog"),
                "source_url":             url,
                "alibaba_url":            url if tpl["source"] == "alibaba" else None,
                "web_identified_model":   web_identified_model,
                "web_citations":          web_citations if tpl["source"] == "alibaba" else [],
                "supplier_links":         supplier_links,
                "marketplace_links":      marketplace_links,   # real product page links
                "best_origin":            origin_country,
            })

            logger.debug("Supplier", s=tpl["name"], unit=unit_kzt, qty=qty,
                         src=price_source, conf=overall_conf, exact=exact_match)

        return results


# ── DB helper ─────────────────────────────────────────────────────────────────

async def _save_supplier_match(
    lot_id, tender_id, name, country, source, product_name,
    unit_price_kzt, lead_time, match_score, source_url,
) -> None:
    async with async_session_factory() as session:
        sup = Supplier(name=name, country=country, source=source,
                       contact_info={"note": "market estimate"})
        session.add(sup)
        await session.flush()
        session.add(SupplierMatch(
            lot_id=lot_id, tender_id=tender_id, supplier_id=sup.id,
            product_name=product_name,
            unit_price=round(unit_price_kzt / settings.USD_TO_KZT, 4),
            currency="USD", unit_price_kzt=unit_price_kzt, moq=1,
            lead_time_days=lead_time, match_score=match_score,
            source_url=source_url,
        ))
        await session.commit()
