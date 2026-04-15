"""
Web Price Enhancer — re-analyzes high-value lots using GPT-4o web search.

Targets lots that:
  - have budget >= budget_min (default 500K₸)
  - are profitable or analyzed
  - have confidence_level != 'high' (or confidence_score < 0.7)
  - have a product category (not 'other')

For each such lot, runs search_product_web() to find real Kazakhstan market prices,
then re-runs profitability calculation with the web-sourced price.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

import structlog
from sqlalchemy import select, and_

from core.database import async_session_factory
from models.tender import Tender
from models.tender_lot import TenderLot
from models.tender_lot_analysis import TenderLotAnalysis
from models.profitability import ProfitabilityAnalysis

logger = structlog.get_logger(__name__)


@dataclass
class EnhanceProgress:
    running: bool = False
    total: int = 0
    done: int = 0
    improved: int = 0
    errors: int = 0
    finished: bool = False
    error_message: Optional[str] = None


_progress = EnhanceProgress()


def get_enhance_progress() -> dict:
    p = _progress
    return {
        "running":  p.running,
        "total":    p.total,
        "done":     p.done,
        "improved": p.improved,
        "errors":   p.errors,
        "finished": p.finished,
        "pct":      round(p.done / p.total * 100, 1) if p.total else 0,
        "error_message": p.error_message,
    }


async def run_web_enhance(
    budget_min: float = 500_000,
    limit: int = 100,
) -> None:
    """
    Batch web-search enhancement for high-value low-confidence lots.
    Re-runs profitability with web-sourced prices.
    Updates _progress for polling.
    """
    global _progress
    from integrations.openai_client.client import OpenAIClient
    from modules.profitability.engine import ProfitabilityEngine

    _progress = EnhanceProgress(running=True)
    client = OpenAIClient()
    engine = ProfitabilityEngine()

    try:
        async with async_session_factory() as session:
            # Fetch analyzed product lots with low/medium confidence and high budget
            q = (
                select(TenderLot, Tender, TenderLotAnalysis, ProfitabilityAnalysis)
                .join(Tender, TenderLot.tender_id == Tender.id)
                .join(TenderLotAnalysis, TenderLotAnalysis.lot_id == TenderLot.id)
                .join(ProfitabilityAnalysis, ProfitabilityAnalysis.lot_id == TenderLot.id)
                .where(
                    TenderLot.budget >= budget_min,
                    TenderLot.category == "product",
                    TenderLot.confidence_level.in_(["low", "medium"]),
                    ProfitabilityAnalysis.price_source != "web_search",  # skip already enhanced
                )
                .order_by(TenderLot.budget.desc())
                .limit(limit)
            )
            rows = (await session.execute(q)).all()

        _progress.total = len(rows)
        logger.info("Web enhance started", total=_progress.total, budget_min=budget_min)

        if not rows:
            _progress.finished = True
            return

        for lot, tender, analysis, prof in rows:
            try:
                # Build search query from analysis data
                product_name = (
                    analysis.product_name
                    or analysis.normalized_name
                    or lot.title
                    or ""
                )
                characteristics = analysis.characteristics or ""
                budget = float(lot.budget) if lot.budget else 0
                quantity = float(lot.quantity) if lot.quantity else 1

                if not product_name:
                    _progress.done += 1
                    continue

                # Call web search
                search_result = await client.search_product_web(
                    product_name=product_name,
                    characteristics=characteristics,
                    budget_per_unit=budget / max(quantity, 1),
                )

                if not search_result or not search_result.get("model_found"):
                    _progress.done += 1
                    continue

                # Extract the best price from search result
                price_kzt = search_result.get("price_kzt") or search_result.get("price_min_kzt")
                if not price_kzt or price_kzt <= 0:
                    _progress.done += 1
                    continue

                # Re-run profitability with web price
                prof_result = await engine.calculate_from_web_price(
                    lot_id=str(lot.id),
                    tender_id=str(lot.tender_id),
                    platform=lot.platform or "",
                    budget=budget,
                    quantity=quantity,
                    unit=lot.unit or "шт",
                    category="product",
                    web_price_kzt=price_kzt,
                    origin=search_result.get("best_market", "CN"),
                    search_result=search_result,
                )

                if prof_result:
                    _progress.improved += 1
                    logger.info(
                        "Web enhance improved lot",
                        lot_id=str(lot.id)[:8],
                        product=product_name[:30],
                        web_price=price_kzt,
                        new_margin=prof_result.get("profit_margin_percent"),
                    )

            except Exception as exc:
                _progress.errors += 1
                logger.error("Web enhance lot error", lot_id=str(lot.id)[:8], error=str(exc))
            finally:
                _progress.done += 1

            await asyncio.sleep(0.5)  # Rate limit — web search is slower

        _progress.finished = True
        logger.info(
            "Web enhance finished",
            total=_progress.total,
            improved=_progress.improved,
            errors=_progress.errors,
        )
        print(
            f"\n{'═'*55}\n"
            f"  WEB PRICE ENHANCE COMPLETE\n"
            f"  Лотов обработано : {_progress.done} / {_progress.total}\n"
            f"  Улучшено         : {_progress.improved}\n"
            f"  Ошибок           : {_progress.errors}\n"
            f"{'═'*55}\n",
            flush=True,
        )

    except Exception as exc:
        _progress.error_message = str(exc)
        logger.error("Web enhance crashed", error=str(exc))
    finally:
        _progress.running = False
