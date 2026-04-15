"""
AI Analysis Cost Tracker.

Estimates and logs USD costs for batch AI analysis runs.
Costs are approximate — based on average token usage per lot (2 API calls).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


# ── Dev mode guard ────────────────────────────────────────────────────────────

class DevModeLimitError(Exception):
    """Raised when a DEV_MODE hard limit (requests or budget) is exceeded."""


class RunBudgetGuard:
    """
    Tracks OpenAI API calls and estimated cost within a single run.

    Usage:
        guard = RunBudgetGuard()
        guard.reset()                        # at the start of each run
        guard.check_and_increment(model)     # before each API call — raises on hard limit
        guard.summary()                      # dict with stats for logging
    """

    def reset(self) -> None:
        self.requests: int = 0
        self.cost_usd: float = 0.0
        self.hard_stopped: bool = False
        self._soft_warned: bool = False

    def __init__(self) -> None:
        self.reset()

    def check_and_increment(self, model: str) -> None:
        """
        Must be called before each OpenAI API call in DEV_MODE.
        - Increments request counter and adds cost estimate (½ lot per call).
        - Logs a warning when soft limit is crossed (once per run).
        - Raises DevModeLimitError when request count or hard budget is exceeded.
        Does nothing when DEV_MODE is False.
        """
        from core.config import settings
        if not settings.DEV_MODE:
            return

        self.requests += 1
        # Each call costs approximately half a lot (2 calls per lot total)
        self.cost_usd += cost_per_lot(model) / 2

        if self.requests > settings.DEV_MAX_OPENAI_REQUESTS_PER_RUN:
            self.hard_stopped = True
            raise DevModeLimitError(
                f"DEV MODE: OpenAI request limit reached "
                f"({self.requests}/{settings.DEV_MAX_OPENAI_REQUESTS_PER_RUN} requests)"
            )

        if self.cost_usd >= settings.DEV_BUDGET_HARD_USD:
            self.hard_stopped = True
            raise DevModeLimitError(
                f"DEV MODE: Hard budget limit reached "
                f"(${self.cost_usd:.4f} >= ${settings.DEV_BUDGET_HARD_USD})"
            )

        if not self._soft_warned and self.cost_usd >= settings.DEV_BUDGET_SOFT_USD:
            self._soft_warned = True
            logger.warning(
                "DEV MODE: soft budget limit crossed",
                cost_usd=round(self.cost_usd, 4),
                soft_limit_usd=settings.DEV_BUDGET_SOFT_USD,
                requests=self.requests,
            )

    def summary(self) -> dict:
        return {
            "openai_requests": self.requests,
            "cost_estimate_usd": round(self.cost_usd, 4),
            "hard_stopped": self.hard_stopped,
        }


# ── Module-level singleton (reset at the start of each batch run) ─────────────
_run_guard = RunBudgetGuard()


def get_run_guard() -> RunBudgetGuard:
    return _run_guard

# ── Cost per lot (2 calls: identify_product + analyze_specification) ──────────
# Approximate averages: ~1 300 input tokens + 400 output tokens per lot

COST_PER_LOT_USD: dict[str, float] = {
    "gpt-4o-mini":              0.0005,
    "gpt-4o-mini-2024-07-18":   0.0005,
    "gpt-4o":                   0.007,
    "gpt-4o-2024-11-20":        0.007,
    "gpt-4":                    0.045,
    "gpt-4-turbo":              0.025,
}
DEFAULT_COST_PER_LOT = 0.007  # fallback (gpt-4o level)

# ── Analysis modes ────────────────────────────────────────────────────────────

ANALYZE_MODES: dict[str, int] = {
    "fast":     10,
    "standard": 50,
    "full":     100,
    "priority": 500,   # high-value lots sorted by budget DESC
}


def get_mode_limit(mode: str) -> int:
    """Return max lots for the given mode."""
    return ANALYZE_MODES.get(mode, ANALYZE_MODES["standard"])


def cost_per_lot(model: str) -> float:
    return COST_PER_LOT_USD.get(model, DEFAULT_COST_PER_LOT)


def estimate_cost(lot_count: int, model: str) -> float:
    """Estimate total USD cost for analyzing lot_count lots."""
    return round(cost_per_lot(model) * lot_count, 4)


# ── Persistent cost log ───────────────────────────────────────────────────────

_DATA_FILE = Path(__file__).parent.parent.parent / "data" / "ai_cost_log.json"


@dataclass
class RunRecord:
    timestamp: str
    lots_processed: int
    cost_usd: float
    model: str
    mode: str = "manual"


class CostTracker:
    """Stores run history in data/ai_cost_log.json (JSON, up to 100 runs)."""

    def __init__(self) -> None:
        _DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict:
        if _DATA_FILE.exists():
            try:
                return json.loads(_DATA_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"runs": [], "total_lots": 0, "total_usd": 0.0}

    def _save(self) -> None:
        _DATA_FILE.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def record_run(
        self,
        lots_processed: int,
        model: str,
        mode: str = "manual",
    ) -> float:
        """Record a completed run. Returns actual cost logged."""
        cost = round(cost_per_lot(model) * lots_processed, 4)
        run = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "lots_processed": lots_processed,
            "cost_usd": cost,
            "model": model,
            "mode": mode,
        }
        self._data["runs"].append(run)
        self._data["total_lots"] = self._data.get("total_lots", 0) + lots_processed
        self._data["total_usd"] = round(self._data.get("total_usd", 0.0) + cost, 4)
        self._data["runs"] = self._data["runs"][-100:]  # keep last 100
        self._save()
        logger.info(
            "AI cost recorded",
            lots=lots_processed,
            cost_usd=cost,
            model=model,
            mode=mode,
        )
        return cost

    def get_stats(self) -> dict:
        return {
            "total_lots_analyzed": self._data.get("total_lots", 0),
            "total_cost_usd": round(self._data.get("total_usd", 0.0), 4),
            "recent_runs": list(reversed(self._data.get("runs", [])[-10:])),
        }


# ── Module-level singleton ────────────────────────────────────────────────────
_tracker: Optional[CostTracker] = None


def get_tracker() -> CostTracker:
    global _tracker
    if _tracker is None:
        _tracker = CostTracker()
    return _tracker
