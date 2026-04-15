"""
Scanner Pipeline — pluggable hook system for post-processing lots.

Each processing stage (AI analysis, supplier discovery, profitability)
registers itself as a pipeline step. The scanner calls them in order.

Architecture:
  Scanner discovers lots → Pipeline runs steps on each lot →
  Steps can set lot.is_analyzed, lot.is_profitable, etc.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Optional
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class PipelineContext:
    """
    Shared context passed through all pipeline steps for a single lot.
    Steps can read/write fields to communicate between stages.
    """
    tender_data: dict
    lot_data: dict
    tender_id: str
    lot_id: str
    platform: str

    # Set by AI Analyzer step
    category: Optional[str] = None
    ai_analysis: Optional[dict] = None

    # Set by Supplier Discovery step
    supplier_matches: Optional[list] = None

    # Set by Profitability step
    profitability: Optional[dict] = None

    # Control flow
    skip_remaining: bool = False   # set True to abort pipeline for this lot
    errors: list = field(default_factory=list)

    def should_skip(self) -> bool:
        return self.skip_remaining

    def add_error(self, step: str, error: str) -> None:
        self.errors.append({"step": step, "error": error})
        logger.warning("Pipeline step error", step=step, lot_id=self.lot_id, error=error)


# Type alias for pipeline step functions
PipelineStep = Callable[[PipelineContext], Awaitable[None]]


class ScannerPipeline:
    """
    Ordered pipeline of async processing steps.
    Steps run sequentially; any step can stop further processing
    by setting ctx.skip_remaining = True.
    """

    def __init__(self):
        self._steps: list[tuple[str, PipelineStep]] = []

    def register(self, name: str, step: PipelineStep) -> None:
        """Register a pipeline step. Steps run in registration order."""
        self._steps.append((name, step))
        logger.info("Pipeline step registered", step=name, position=len(self._steps))

    async def run(self, ctx: PipelineContext) -> PipelineContext:
        """
        Run all registered steps on the given context.
        Returns the (mutated) context after all steps complete.
        """
        for name, step in self._steps:
            if ctx.should_skip():
                logger.debug("Pipeline short-circuited", remaining_step=name, lot_id=ctx.lot_id)
                break
            try:
                await step(ctx)
            except Exception as e:
                ctx.add_error(name, str(e))
                # Non-fatal — continue to next step unless it's a critical one
                logger.error("Pipeline step failed", step=name, lot_id=ctx.lot_id, error=str(e))
        return ctx

    async def run_batch(
        self,
        contexts: list[PipelineContext],
        concurrency: int = 3,
    ) -> list[PipelineContext]:
        """
        Run pipeline on a batch of contexts with controlled concurrency.
        Returns list of completed contexts.
        """
        sem = asyncio.Semaphore(concurrency)

        async def run_one(ctx: PipelineContext) -> PipelineContext:
            async with sem:
                return await self.run(ctx)

        return await asyncio.gather(*[run_one(ctx) for ctx in contexts])


# ── Global pipeline instance (populated by each module at startup) ────────────
pipeline = ScannerPipeline()
