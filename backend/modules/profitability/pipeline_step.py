"""
Profitability pipeline step — bridge between ProfitabilityEngine and ScannerPipeline.

Runs after the AI analysis step. Reads ctx.ai_analysis (product specs extracted by GPT-4o),
runs the full profitability calculation, and writes the result to ctx.profitability.

Skips lots that:
  - have no budget
  - were classified as "other" by the AI step (ctx.skip_remaining already set)
  - have no AI analysis result (engine falls back to keyword-only mode)
"""
from __future__ import annotations

import uuid
from typing import Optional
import structlog

from modules.scanner.pipeline import ScannerPipeline, PipelineContext

logger = structlog.get_logger(__name__)

_engine: Optional[object] = None


def _get_engine():
    global _engine
    if _engine is None:
        from modules.profitability.engine import ProfitabilityEngine
        _engine = ProfitabilityEngine()
    return _engine


async def profitability_step(ctx: PipelineContext) -> None:
    """
    Pipeline step: run profitability analysis on a lot.
    Sets ctx.profitability with the full breakdown dict.
    """
    # Budget: prefer lot-level, fall back to tender-level
    budget_raw = ctx.lot_data.get("budget") or ctx.tender_data.get("budget")
    if not budget_raw:
        logger.debug("Lot has no budget, skipping profitability", lot_id=ctx.lot_id[:8])
        return

    try:
        budget = float(budget_raw)
    except (TypeError, ValueError):
        logger.warning("Invalid budget value", lot_id=ctx.lot_id[:8], budget=budget_raw)
        return

    # AI analysis from previous step (may be None if no OpenAI key)
    ai_analysis = ctx.ai_analysis or {}

    # Pass raw spec text so the engine can run the product resolver
    spec_text = (
        ctx.lot_data.get("technical_spec_text")
        or ctx.lot_data.get("description")
        or ctx.tender_data.get("description")
        or ""
    )
    lot_title = ctx.lot_data.get("title") or ctx.tender_data.get("title") or ""

    engine = _get_engine()
    result = await engine.analyze(
        budget=budget,
        analysis=ai_analysis,
        spec_text=spec_text,
        lot_title=lot_title,
        lot_id=uuid.UUID(ctx.lot_id),
        tender_id=uuid.UUID(ctx.tender_id),
    )

    if result:
        ctx.profitability = result
        logger.info(
            "Profitability step done",
            lot_id=ctx.lot_id[:8],
            margin=f"{result.get('profit_margin_percent', 0):.1f}%",
            profitable=result.get("is_profitable"),
        )


def register_profitability_step(pipeline: ScannerPipeline) -> None:
    pipeline.register("profitability", profitability_step)
