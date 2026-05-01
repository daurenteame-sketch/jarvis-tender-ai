"""
Scan control routes — manual trigger, status, and AI analysis control.
All endpoints require authentication. Trigger/recalculate require admin role.
"""
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from core.config import settings
from modules.scanner.scanner import TenderScanner
from modules.profitability.recalculate import run_recalculation, get_progress
from modules.ai_analyzer.batch_analyzer import (
    get_estimate, run_batch_analysis, get_progress as get_analyze_progress,
)
from modules.ai_analyzer.cost_tracker import get_tracker
from core.deps import get_current_user, require_admin
from models.user import User

router = APIRouter(prefix="/scan", tags=["scan"])
_scanner = TenderScanner()

# In-memory scan progress. Single-run state (we never run two scans in parallel)
# so a global dict is enough — no need for Redis here.
_scan_state: dict = {
    "running":      False,
    "finished":     False,
    "total":        0,        # planned upper bound (SCAN_LIMIT × 2 platforms)
    "done":         0,        # tenders observed so far across platforms
    "lots_new":     0,        # populated when scan completes
    "tenders_new":  0,
    "started_at":   None,
    "finished_at":  None,
    "error":        None,
}


@router.post("/trigger")
async def trigger_scan(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_admin),
):
    """Manually trigger a tender scan."""
    if _scan_state["running"]:
        return {"status": "already_running", "message": "Сканирование уже выполняется"}

    # Plan an upper bound: each platform processes up to SCAN_LIMIT tenders.
    planned_total = max(1, settings.SCAN_LIMIT) * 2  # goszakup + zakupsk

    _scan_state.update({
        "running":      True,
        "finished":     False,
        "total":        planned_total,
        "done":         0,
        "lots_new":     0,
        "tenders_new":  0,
        "started_at":   datetime.now(timezone.utc).isoformat(),
        "finished_at":  None,
        "error":        None,
    })

    async def run():
        try:
            results = await _scanner.run_full_scan()
            # results: {"goszakup": {...}, "zakupsk": {...}}
            tenders_new = sum(r.get("tenders_new", 0) for r in results.values())
            lots_new    = sum(r.get("lots_new", 0)    for r in results.values())
            tenders_seen = sum(r.get("tenders_found", 0) for r in results.values())
            _scan_state.update({
                "running":     False,
                "finished":    True,
                "done":        min(tenders_seen, _scan_state["total"]),
                "tenders_new": tenders_new,
                "lots_new":    lots_new,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as exc:
            _scan_state.update({
                "running":     False,
                "finished":    True,
                "error":       str(exc)[:200],
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })

    background_tasks.add_task(run)
    return {
        "status":  "started",
        "message": "Сканирование запущено",
        "total":   planned_total,
    }


@router.get("/status")
async def get_scan_status(current_user: User = Depends(get_current_user)):
    """
    Current scan state — used by the dashboard progress bar.

    Fields:
      running     true while scan is in progress
      finished    true after the most recent run completed (sticks until next trigger)
      total       planned upper bound: SCAN_LIMIT × number of platforms
      done        tenders processed (only updated on completion at the moment)
      pct         derived percentage (0-100)
      tenders_new / lots_new   results once finished
      started_at / finished_at ISO timestamps
      error       error message if the run blew up
    """
    pct = 0
    if _scan_state["total"] > 0:
        pct = min(100, int(_scan_state["done"] * 100 / _scan_state["total"]))
    # If running but done==0, show indeterminate-ish 5% so the bar is visible
    if _scan_state["running"] and pct == 0:
        pct = 5
    if _scan_state["finished"]:
        pct = 100
    return {
        # Old shape kept for backwards-compat
        "is_running": _scan_state["running"],
        # New extended shape
        "running":     _scan_state["running"],
        "finished":    _scan_state["finished"],
        "total":       _scan_state["total"],
        "done":        _scan_state["done"],
        "pct":         pct,
        "tenders_new": _scan_state["tenders_new"],
        "lots_new":    _scan_state["lots_new"],
        "started_at":  _scan_state["started_at"],
        "finished_at": _scan_state["finished_at"],
        "error":       _scan_state["error"],
    }


@router.post("/recalculate-profitability")
async def trigger_recalculate(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_admin),
):
    """
    Recalculate profitability for all existing lots using the updated margin logic.
    Runs in the background; poll /scan/recalculate-status for progress.
    """
    progress = get_progress()
    if progress["running"]:
        return {"status": "already_running", "progress": progress}

    background_tasks.add_task(run_recalculation)
    return {"status": "started", "message": "Пересчёт прибыльности запущен"}


@router.get("/recalculate-status")
async def get_recalculate_status(current_user: User = Depends(get_current_user)):
    """Return current recalculation progress."""
    return get_progress()


# ── AI batch analysis ──────────────────────────────────────────────────────────

@router.get("/analyze-estimate")
async def analyze_estimate(
    mode: str = Query("standard", pattern="^(fast|standard|full)$"),
    current_user: User = Depends(get_current_user),
):
    """
    Return cost estimate for AI analysis without starting it.
    Shows: unanalyzed count, will_analyze count, estimated USD cost.
    """
    return await get_estimate(mode)


@router.post("/analyze-lots")
async def trigger_analyze_lots(
    background_tasks: BackgroundTasks,
    mode: str = Query("standard", pattern="^(fast|standard|full|priority)$"),
    budget_min: float = Query(None, ge=0, description="Only analyze lots with budget >= this value"),
    current_user: User = Depends(require_admin),
):
    """
    Start batch AI analysis for unanalyzed lots.
    'priority' mode processes up to 500 lots sorted by budget DESC.
    budget_min filters to only high-value lots.
    Returns immediately; poll /scan/analyze-status for progress.
    """
    progress = get_analyze_progress()
    if progress["running"]:
        return {"status": "already_running", "progress": progress}

    background_tasks.add_task(run_batch_analysis, mode, budget_min)
    estimate = await get_estimate(mode)
    return {
        "status":            "started",
        "mode":              mode,
        "budget_min":        budget_min,
        "will_analyze":      estimate["will_analyze"],
        "cost_estimate_usd": estimate["cost_estimate_usd"],
    }


@router.get("/analyze-status")
async def get_analyze_status(current_user: User = Depends(get_current_user)):
    """Return current AI batch analysis progress."""
    return get_analyze_progress()


@router.get("/ai-cost-log")
async def get_ai_cost_log(current_user: User = Depends(require_admin)):
    """Return AI analysis cost history and totals."""
    return get_tracker().get_stats()


# ── Web price enhancement ──────────────────────────────────────────────────────

@router.post("/web-enhance")
async def trigger_web_enhance(
    background_tasks: BackgroundTasks,
    budget_min: float = Query(500_000, ge=0, description="Only enhance lots with budget >= this"),
    limit: int = Query(50, ge=1, le=200, description="Max lots to enhance"),
    current_user: User = Depends(require_admin),
):
    """
    Re-analyze high-value low-confidence PRODUCT lots using GPT-4o web search.
    Finds real Kazakhstan market prices and recalculates profitability.
    Returns immediately; poll /scan/web-enhance-status for progress.
    """
    from modules.ai_analyzer.web_enhancer import get_enhance_progress, run_web_enhance
    progress = get_enhance_progress()
    if progress["running"]:
        return {"status": "already_running", "progress": progress}

    background_tasks.add_task(run_web_enhance, budget_min, limit)
    return {
        "status":     "started",
        "budget_min": budget_min,
        "limit":      limit,
        "message":    f"Web price enhancement запущен (лоты ≥{budget_min/1e6:.1f}M₸, лимит {limit})",
    }


@router.get("/web-enhance-status")
async def get_web_enhance_status(current_user: User = Depends(get_current_user)):
    """Return current web enhance progress."""
    from modules.ai_analyzer.web_enhancer import get_enhance_progress
    return get_enhance_progress()
