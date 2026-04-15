"""
TenderScanner — top-level orchestrator for the scanning pipeline.

Coordinates GosZakupScanner and ZakupSKScanner in parallel.
Each platform scanner handles its own:
  - API client lifecycle
  - Incremental state (offset / page)
  - ScanRun records
  - Document enrichment
  - Pipeline execution

This class owns shared resources (deduplicator, state_manager) and
passes them down to the platform scanners.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import structlog

from modules.scanner.deduplicator import TenderDeduplicator
from modules.scanner.state_manager import ScanStateManager
from modules.scanner.goszakup_scanner import GosZakupScanner
from modules.scanner.sk_scanner import ZakupSKScanner

logger = structlog.get_logger(__name__)


class TenderScanner:
    """
    Orchestrates tender scanning across all platforms in parallel.

    Usage:
        scanner = TenderScanner()
        results = await scanner.run_full_scan()
    """

    def __init__(self) -> None:
        self.deduplicator = TenderDeduplicator()
        self.state_manager = ScanStateManager()
        self._goszakup = GosZakupScanner(self.deduplicator, self.state_manager)
        self._zakupsk = ZakupSKScanner(self.deduplicator, self.state_manager)

    async def run_full_scan(self) -> dict:
        """
        Run one complete scan cycle across all platforms in parallel.
        Returns per-platform stats dict.

        Example return value:
            {
                "goszakup": {"tenders_found": 120, "lots_new": 45, "profitable_found": 7, ...},
                "zakupsk":  {"tenders_found": 80,  "lots_new": 12, "profitable_found": 2, ...},
            }
        """
        logger.info("=== JARVIS scan cycle started ===")

        # Reset in-memory deduplication cache at the start of each cycle
        self.deduplicator.reset()

        gz_task = asyncio.create_task(self._run_platform("goszakup", self._goszakup))
        sk_task = asyncio.create_task(self._run_platform("zakupsk", self._zakupsk))

        gz_result, sk_result = await asyncio.gather(gz_task, sk_task, return_exceptions=False)

        results = {
            "goszakup": gz_result,
            "zakupsk": sk_result,
        }

        total_profitable = gz_result.get("profitable_found", 0) + sk_result.get("profitable_found", 0)
        total_new_lots = gz_result.get("lots_new", 0) + sk_result.get("lots_new", 0)

        logger.info(
            "=== Scan cycle complete ===",
            total_profitable=total_profitable,
            total_new_lots=total_new_lots,
        )
        return results

    async def _run_platform(self, name: str, scanner) -> dict:
        """Wrapper that catches platform-level errors and returns an error stats dict."""
        try:
            return await scanner.run()
        except Exception as exc:
            logger.error("Platform scan raised an exception", platform=name, error=str(exc))
            return {
                "tenders_found": 0,
                "tenders_new": 0,
                "lots_found": 0,
                "lots_new": 0,
                "profitable_found": 0,
                "errors": 1,
                "error": str(exc),
            }
