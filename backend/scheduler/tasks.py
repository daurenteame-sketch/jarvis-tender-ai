"""
APScheduler configuration — scheduled jobs for JARVIS.

Jobs:
  hourly_tender_scan   — full scan across all platforms every SCAN_INTERVAL_MINUTES
  daily_summary        — morning report at 09:00 Almaty with yesterday's stats
  health_check         — lightweight DB ping every 5 minutes
  startup_scan         — one-time scan 20 seconds after startup

All jobs run in the same event loop as FastAPI (AsyncIOScheduler).
Imports are lazy to avoid circular dependency issues at module load time.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import structlog

from core.config import settings

logger = structlog.get_logger(__name__)

# ── Lazy singletons (avoid circular imports) ──────────────────────────────────

_scanner: Optional[object] = None
_notifier: Optional[object] = None

# Consecutive failure counter for escalating alerts
_consecutive_failures = 0
MAX_FAILURES_BEFORE_ALERT = 3

# ── Auto-alert dedup state ─────────────────────────────────────────────────────
_sent_ids: set[str] = set()   # URLs already notified, reset on restart
PROFITABLE_KEYWORDS = ["фасад", "ремонт", "оборудование", "мебель", "строительство"]
MIN_NET_PROFIT = 300_000      # ₸

# ── Mock tender auto-notify dedup (reset on restart) ──────────────────────────
_mock_sent_urls: set[str] = set()

# ── Configure-prompt throttle: send "please set up filters" at most once ──────
_configure_prompt_sent: set[str] = set()  # chat_ids that already got the prompt


def _get_scanner():
    global _scanner
    if _scanner is None:
        from modules.scanner.scanner import TenderScanner
        _scanner = TenderScanner()
    return _scanner


def _get_notifier():
    global _notifier
    if _notifier is None:
        from modules.notifications.telegram import TelegramNotifier
        _notifier = TelegramNotifier()
    return _notifier


# ── Job: hourly scan ──────────────────────────────────────────────────────────

async def run_tender_scan() -> None:
    """
    Main scheduled job: one full scan cycle across all platforms.
    Tracks consecutive failures and sends a Telegram alert after N failures.
    Sends a brief Telegram summary if profitable lots were found.
    """
    global _consecutive_failures

    started_at = datetime.now(timezone.utc)
    logger.info("Scheduled scan triggered", time=started_at.isoformat())

    try:
        scanner = _get_scanner()
        results = await scanner.run_full_scan()

        _consecutive_failures = 0

        total_profitable = sum(
            r.get("profitable_found", 0)
            for r in results.values()
            if isinstance(r, dict)
        )
        total_new_lots = sum(
            r.get("lots_new", 0)
            for r in results.values()
            if isinstance(r, dict)
        )
        total_errors = sum(
            r.get("errors", 0)
            for r in results.values()
            if isinstance(r, dict)
        )

        elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()

        logger.info(
            "Scan cycle finished",
            profitable=total_profitable,
            new_lots=total_new_lots,
            errors=total_errors,
            elapsed_s=round(elapsed, 1),
        )

        # Notify if any profitable lots were found
        if total_profitable > 0:
            await _send_scan_summary(results, total_profitable, total_new_lots, elapsed)

    except Exception as exc:
        _consecutive_failures += 1
        logger.error(
            "Scan cycle failed",
            error=str(exc),
            consecutive_failures=_consecutive_failures,
        )

        if _consecutive_failures >= MAX_FAILURES_BEFORE_ALERT:
            await _send_error_alert(
                f"Сканирование упало {_consecutive_failures} раз подряд.\n"
                f"Ошибка: {str(exc)[:300]}"
            )


# ── Job: profitable tender auto-alert ────────────────────────────────────────

def _test_telegram_send() -> None:
    """
    Diagnostic: send a message via raw HTTP (requests), no telegram library.
    Prints full status + response body so we can see exactly what Telegram returns.
    """
    import requests as _requests

    from core.chat_id_store import load_chat_id
    token   = settings.TELEGRAM_BOT_TOKEN
    chat_id = load_chat_id()

    print(f"🔑 BOT_TOKEN present: {bool(token)} (ends: ...{token[-6:] if token else 'EMPTY'})", flush=True)
    print(f"FINAL CHAT ID: {chat_id if chat_id else 'NOT SET'}", flush=True)

    if not token:
        print("❌ TELEGRAM_BOT_TOKEN is empty — check .env", flush=True)
        return
    if not chat_id:
        print("NO CHAT ID — send any message to the bot first", flush=True)
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    print(f"🌐 POST {url[:60]}...", flush=True)

    try:
        resp = _requests.post(
            url,
            json={"chat_id": chat_id, "text": "🚀 DIRECT HTTP TEST"},
            timeout=10,
        )
        print(f"📡 STATUS: {resp.status_code}", flush=True)
        print(f"📄 BODY:   {resp.text[:300]}", flush=True)
    except Exception as exc:
        print(f"❌ HTTP ERROR: {exc}", flush=True)
        logger.warning("_test_telegram_send HTTP failed", error=str(exc))


async def check_profitable_tenders() -> None:
    """
    Every 10 minutes: search goszakup for profitable tenders and notify via Telegram.
    Deduplicates by URL so each tender is sent at most once per process lifetime.
    """
    global _sent_ids

    print("🔥 ALERT FUNCTION RUNNING", flush=True)
    print("Checking profitable tenders...", flush=True)

    # Respect pause setting before doing any work
    try:
        from core.chat_id_store import load_chat_id
        from core.user_settings import get_settings
        _cid = load_chat_id()
        if _cid and get_settings(_cid).paused:
            logger.debug("check_profitable_tenders: stream paused, skipping")
            return
    except Exception:
        pass

    _test_telegram_send()

    loop = asyncio.get_running_loop()

    try:
        from modules.tenders.search import search_tenders

        found_count = 0
        for keyword in PROFITABLE_KEYWORDS:
            try:
                results: list[dict] = await loop.run_in_executor(
                    None, search_tenders, keyword
                )
            except Exception as exc:
                logger.warning("search_tenders failed", keyword=keyword, error=str(exc))
                continue

            for t in results:
                url = t.get("url", "")
                if not url or url in _sent_ids:
                    continue

                if t.get("net_profit", 0) > MIN_NET_PROFIT:
                    title      = t.get("title", "Без названия")
                    price      = t.get("price", 0)
                    net_profit = t.get("net_profit", 0)

                    price_str  = f"{price:,.0f}".replace(",", " ") if isinstance(price, (int, float)) else str(price)
                    profit_str = f"{net_profit:,.0f}".replace(",", " ")

                    message = (
                        "🔥 *Найден выгодный тендер*\n\n"
                        f"📌 {title}\n"
                        f"Сумма: {price_str} ₸\n"
                        f"Маржа: {profit_str} ₸\n"
                        f"Рекомендация: ЗАХОДИТЬ ✅\n\n"
                        f"🔗 {url}"
                    )

                    try:
                        notifier = _get_notifier()
                        await notifier.send_message(message)
                        _sent_ids.add(url)
                        found_count += 1
                        logger.info("Profitable tender alert sent", url=url, net_profit=net_profit)
                    except Exception as exc:
                        logger.error("Failed to send profitable tender alert", error=str(exc))

        logger.info("check_profitable_tenders finished", alerts_sent=found_count)

    except Exception as exc:
        logger.error("check_profitable_tenders crashed", error=str(exc))


# ── Job: daily morning summary ────────────────────────────────────────────────

async def run_daily_summary() -> None:
    """
    Daily report job (09:00 Almaty). Pulls yesterday's stats from the DB
    and sends a digest via Telegram.
    """
    logger.info("Daily summary job triggered")
    try:
        stats = await _collect_daily_stats()
        message = _format_daily_summary(stats)
        notifier = _get_notifier()
        await notifier.send_message(message)
        logger.info("Daily summary sent")
    except Exception as exc:
        logger.error("Daily summary failed", error=str(exc))


async def _collect_daily_stats() -> dict:
    """Query DB for last 24h scan results."""
    from sqlalchemy import select, func
    from core.database import async_session_factory
    from models.scan_run import ScanRun
    from models.tender_lot import TenderLot

    since = datetime.now(timezone.utc) - timedelta(hours=24)

    async with async_session_factory() as session:
        # Scan runs in last 24h
        runs_result = await session.execute(
            select(
                func.count(ScanRun.id).label("total_runs"),
                func.sum(ScanRun.tenders_found).label("tenders_found"),
                func.sum(ScanRun.tenders_new).label("tenders_new"),
                func.sum(ScanRun.profitable_found).label("profitable_found"),
            ).where(ScanRun.started_at >= since)
        )
        run_row = runs_result.one()

        # New profitable lots in last 24h
        profitable_result = await session.execute(
            select(func.count(TenderLot.id)).where(
                TenderLot.is_profitable == True,
                TenderLot.first_seen_at >= since,
            )
        )
        profitable_lots = profitable_result.scalar() or 0

    return {
        "total_runs": run_row.total_runs or 0,
        "tenders_found": int(run_row.tenders_found or 0),
        "tenders_new": int(run_row.tenders_new or 0),
        "profitable_found": int(run_row.profitable_found or 0),
        "profitable_lots": profitable_lots,
        "date": (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%d.%m.%Y"),
    }


def _format_daily_summary(stats: dict) -> str:
    profitable = stats["profitable_lots"]
    emoji = "🟢" if profitable > 0 else "⚪"

    lines = [
        f"{emoji} *JARVIS — Дневной отчёт за {stats['date']}*",
        "",
        f"📡 Циклов сканирования: {stats['total_runs']}",
        f"📋 Тендеров просмотрено: {stats['tenders_found']}",
        f"🆕 Новых тендеров: {stats['tenders_new']}",
        f"💰 Прибыльных лотов: *{profitable}*",
        "",
        "Хорошего дня! JARVIS следит за рынком." if profitable == 0
        else f"Есть возможности! Откройте дашборд для деталей.",
    ]
    return "\n".join(lines)


# ── Job: health check ─────────────────────────────────────────────────────────

async def run_health_check() -> None:
    """
    Lightweight job every 5 minutes.
    Pings the database to ensure connectivity. Sends Telegram alert on failure.
    """
    try:
        from core.database import async_session_factory
        from sqlalchemy import text
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        logger.debug("Health check passed")
    except Exception as exc:
        logger.error("Health check FAILED — DB unreachable", error=str(exc))
        await _send_error_alert(f"⚠️ JARVIS: база данных недоступна!\n{str(exc)[:200]}")


# ── Telegram helpers ──────────────────────────────────────────────────────────

async def _send_scan_summary(
    results: dict,
    total_profitable: int,
    total_new_lots: int,
    elapsed_s: float,
) -> None:
    """Send brief Telegram message when profitable lots found."""
    try:
        lines = [
            f"💰 *JARVIS нашёл прибыльные лоты!*",
            "",
            f"🏆 Прибыльных лотов: *{total_profitable}*",
            f"🆕 Новых лотов всего: {total_new_lots}",
            "",
        ]
        for platform, r in results.items():
            if not isinstance(r, dict):
                continue
            p = r.get("profitable_found", 0)
            n = r.get("lots_new", 0)
            name = "ГосЗакуп" if platform == "goszakup" else "Закуп СК"
            if n > 0:
                lines.append(f"  • {name}: {p} прибыльных / {n} новых")

        lines += ["", f"⏱ Время сканирования: {elapsed_s:.0f} сек"]
        lines += ["", "Откройте дашборд для деталей ↗"]

        notifier = _get_notifier()
        await notifier.send_message("\n".join(lines))
    except Exception as exc:
        logger.warning("Failed to send scan summary notification", error=str(exc))


async def _send_error_alert(message: str) -> None:
    """Send error alert to Telegram. Swallows exceptions to avoid masking original errors."""
    try:
        notifier = _get_notifier()
        await notifier.send_error_alert(message)
    except Exception as exc:
        logger.warning("Failed to send error alert", error=str(exc))


# ── Job: new-tender Telegram notifications ────────────────────────────────────

async def notify_new_tenders() -> None:
    """
    Every 60 seconds: find tenders not yet notified, send a Telegram message,
    record in Notifications table to prevent duplicates.
    """
    from sqlalchemy import select
    from telegram import Bot
    from core.database import async_session_factory
    from models.tender import Tender
    from models.tender_lot import TenderLot
    from models.profitability import ProfitabilityAnalysis
    from models.notification import Notification

    if not settings.TELEGRAM_BOT_TOKEN or not _get_chat_id():
        logger.warning("notify_new_tenders: no bot token or chat_id, skipping")
        return

    # Respect pause setting
    try:
        from core.user_settings import get_settings
        if get_settings(_get_chat_id()).paused:
            logger.debug("notify_new_tenders: stream paused, skipping")
            return
    except Exception:
        pass

    try:
        async with async_session_factory() as session:
            # tender_ids that already have a new-tender notification
            sent_subq = (
                select(Notification.tender_id)
                .where(
                    Notification.tender_id.isnot(None),
                    Notification.channel == "telegram_new_tender",
                )
                .scalar_subquery()
            )

            rows = await session.execute(
                select(Tender)
                .where(
                    Tender.id.notin_(sent_subq),
                    Tender.status == "published",
                )
                .order_by(Tender.first_seen_at.desc())
                .limit(5)
            )
            new_tenders = rows.scalars().all()

        if not new_tenders:
            logger.debug("notify_new_tenders: no new tenders")
            return

        logger.info("notify_new_tenders: found new tenders", count=len(new_tenders))
        bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)

        for tender in new_tenders:
            try:
                # Fetch lots + profitability for this tender
                async with async_session_factory() as session:
                    lot_rows = await session.execute(
                        select(TenderLot, ProfitabilityAnalysis)
                        .join(
                            ProfitabilityAnalysis,
                            ProfitabilityAnalysis.lot_id == TenderLot.id,
                            isouter=True,
                        )
                        .where(TenderLot.tender_id == tender.id)
                    )
                    lots = lot_rows.all()

                total_lots = len(lots)
                profitable_lots = [
                    (lot, prof) for lot, prof in lots
                    if prof and prof.profit_margin_percent and float(prof.profit_margin_percent) > 0
                ]
                best_margin = (
                    max(float(p.profit_margin_percent) for _, p in profitable_lots)
                    if profitable_lots else None
                )

                budget_str = (
                    f"{float(tender.budget):,.0f} ₸".replace(",", " ")
                    if tender.budget else "—"
                )
                platform_label = "🏛 GosZakup" if tender.platform == "goszakup" else "🏢 Zakup SK"
                deadline_str = (
                    tender.deadline_at.strftime("%d.%m.%Y") if tender.deadline_at else "не указано"
                )

                link = ""
                if tender.platform == "goszakup" and tender.external_id:
                    link = f"\n🔗 [Открыть тендер](https://goszakup.gov.kz/ru/announce/index/{tender.external_id})"

                margin_line = (
                    f"\n📈 Лучшая маржа: *{best_margin:.1f}%* ({'✅' if best_margin >= 50 else '⚠️'})"
                    if best_margin is not None else ""
                )

                message = (
                    f"🆕 *Новый тендер* | {platform_label}\n"
                    f"─────────────────────────────\n"
                    f"📌 {tender.title[:120]}\n"
                    f"🏢 {tender.customer_name or '—'}\n"
                    f"💰 Бюджет: *{budget_str}*\n"
                    f"📦 Лотов: {total_lots} | прибыльных: {len(profitable_lots)}"
                    f"{margin_line}\n"
                    f"📅 Дедлайн: {deadline_str}"
                    f"{link}"
                )

                chat_id = _get_chat_id()
                print(f"FINAL CHAT ID: {chat_id}", flush=True)
                await bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="Markdown",
                    disable_web_page_preview=False,
                )

                # Record sent notification — prevents re-sending
                async with async_session_factory() as session:
                    session.add(Notification(
                        tender_id=tender.id,
                        channel="telegram_new_tender",
                        recipient=str(chat_id),
                        message=message,
                        status="sent",
                    ))
                    await session.commit()

                logger.info(
                    "New tender notification sent",
                    tender_id=str(tender.id),
                    title=tender.title[:60],
                    lots=total_lots,
                    profitable=len(profitable_lots),
                )

            except Exception as exc:
                logger.error(
                    "Failed to send tender notification",
                    tender_id=str(tender.id),
                    error=str(exc),
                )

    except Exception as exc:
        logger.error("notify_new_tenders crashed", error=str(exc))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_price(price: int | float) -> str:
    return f"{price:,.0f}".replace(",", " ")


def _get_chat_id() -> str | int | None:
    """Return the best available chat_id.

    Priority:
      1. data/chat_ids.json (persisted across restarts)
      2. LAST_CHAT_ID from bot_handler (in-memory, current session)
      3. TELEGRAM_CHAT_ID from settings (.env) as last resort
    """
    try:
        from core.chat_id_store import load_chat_id
        stored = load_chat_id()
        if stored:
            print(f"USING CHAT ID: {stored} (from file)", flush=True)
            return stored
    except Exception:
        pass

    try:
        from modules.notifications.bot_handler import LAST_CHAT_ID
        if LAST_CHAT_ID:
            print(f"USING CHAT ID: {LAST_CHAT_ID} (from memory)", flush=True)
            return LAST_CHAT_ID
    except Exception:
        pass

    fallback = settings.TELEGRAM_CHAT_ID or None
    if fallback:
        print(f"USING CHAT ID: {fallback} (from .env)", flush=True)
    return fallback


# ── Job: profitable tender auto-notify every 5 minutes ────────────────────────

async def send_tenders_to_telegram(tenders: list[dict]) -> int:
    """Send each profitable tender via send_to_telegram() — single source of truth for chat_id."""
    from core.chat_id_store import send_to_telegram

    sent = 0
    for tender in tenders:
        text = (
            "🔥 *Новый тендер*\n\n"
            f"📦 Название: {tender['title']}\n"
            f"💰 Сумма: {_fmt_price(tender['price'])} тг\n"
            f"📍 Источник: {tender['source']}\n"
            f"🔗 Ссылка: {tender['url']}"
        )
        ok = await send_to_telegram(text)
        if ok:
            sent += 1
            logger.info(
                "send_tenders_to_telegram: sent",
                title=tender["title"][:60],
                price=tender["price"],
            )
        else:
            logger.error("send_tenders_to_telegram: failed for", title=tender["title"][:60])

    return sent


async def auto_notify_new_tenders() -> None:
    """
    Every 5 minutes:
      1. Log "checking tenders..."
      2. Fetch profitable tenders via get_new_tenders()
      3. Skip already-sent ones (dedup by URL in _mock_sent_urls)
      4. Send new ones to Telegram
      5. Log found / sent counts
    """
    global _mock_sent_urls
    from modules.scanner.tender_scanner import get_new_tenders

    logger.info("auto_notify_new_tenders: checking tenders...")

    try:
        from core.user_settings import tender_matches, can_send, is_configured, get_settings
        from core.chat_id_store import load_chat_id

        chat_id = _get_chat_id()

        # If user paused the stream — skip silently
        if chat_id and get_settings(chat_id).paused:
            logger.debug("auto_notify: stream paused, skipping", chat_id=chat_id)
            return

        # If filters not configured (min_price=0) — send one-time prompt and skip
        if chat_id and not is_configured(chat_id):
            key = str(chat_id)
            if key not in _configure_prompt_sent:
                _configure_prompt_sent.add(key)
                try:
                    from modules.notifications.bot_handler import send_configure_prompt
                    await send_configure_prompt(int(chat_id))
                    logger.info("auto_notify: sent configure prompt", chat_id=chat_id)
                except Exception as exc:
                    logger.warning("auto_notify: configure prompt failed", error=str(exc))
            return

        all_tenders = get_new_tenders()

        # Dedup: skip already sent
        unseen = [t for t in all_tenders if t["url"] not in _mock_sent_urls]

        # User filter
        if chat_id:
            filtered = [t for t in unseen if tender_matches(t, chat_id)]
        else:
            filtered = unseen

        logger.info(
            "auto_notify_new_tenders: scan result",
            found=len(all_tenders),
            unseen=len(unseen),
            after_filter=len(filtered),
        )

        if not filtered:
            return

        # Anti-spam: respect max_per_hour
        if chat_id and not can_send(chat_id):
            logger.info("auto_notify_new_tenders: rate limit reached, skipping")
            return

        sent = await send_tenders_to_telegram(filtered) or 0

        for t in filtered:
            _mock_sent_urls.add(t["url"])

        logger.info("auto_notify_new_tenders: done", sent=sent)

    except Exception as exc:
        logger.error("auto_notify_new_tenders crashed", error=str(exc))


async def send_startup_test_notification() -> None:
    """Send startup message to verify Telegram connectivity."""
    from core.chat_id_store import send_to_telegram

    ok = await send_to_telegram("🚀 бот запущен и готов к поиску тендеров", bypass_pause=True)
    if ok:
        logger.info("Startup notification sent")
    else:
        logger.warning("Startup notification skipped — no chat_id yet (send any message to the bot first)")


# ── Scheduler factory ─────────────────────────────────────────────────────────

def create_scheduler() -> AsyncIOScheduler:
    """
    Create and configure the APScheduler instance.
    Call scheduler.start() from the FastAPI lifespan handler.
    """
    scheduler = AsyncIOScheduler(
        timezone="Asia/Almaty",
        job_defaults={
            "coalesce": True,           # merge missed runs into one
            "max_instances": 1,         # never run the same job twice simultaneously
            "misfire_grace_time": 300,  # allow up to 5 min late start
        },
    )

    # ── Hourly tender scan (disabled in DEV_MODE — manual only) ──────────────
    if settings.DEV_MODE:
        logger.info(
            "DEV_MODE: auto scan disabled — use POST /api/v1/scan/trigger manually",
        )
    else:
        scheduler.add_job(
            run_tender_scan,
            trigger=IntervalTrigger(
                minutes=settings.SCAN_INTERVAL_MINUTES,
                timezone="Asia/Almaty",
            ),
            id="hourly_tender_scan",
            replace_existing=True,
            name="Hourly tender scan (all platforms)",
        )

    # ── Daily morning summary at 09:00 Almaty ────────────────────────────────
    scheduler.add_job(
        run_daily_summary,
        trigger=CronTrigger(hour=9, minute=0, timezone="Asia/Almaty"),
        id="daily_summary",
        replace_existing=True,
        name="Daily morning summary",
    )

    # ── Health check every 5 minutes ─────────────────────────────────────────
    scheduler.add_job(
        run_health_check,
        trigger=IntervalTrigger(minutes=5, timezone="Asia/Almaty"),
        id="health_check",
        replace_existing=True,
        name="DB health check",
    )

    # ── Profitable tender auto-alert every 10 minutes ─────────────────────────
    scheduler.add_job(
        check_profitable_tenders,
        trigger=IntervalTrigger(minutes=10, timezone="Asia/Almaty"),
        id="profitable_tender_alert",
        replace_existing=True,
        name="Profitable tender auto-alert",
    )

    # ── New-tender Telegram notifications every 60 seconds ────────────────────
    scheduler.add_job(
        notify_new_tenders,
        trigger=IntervalTrigger(seconds=60),
        id="new_tender_notifications",
        replace_existing=True,
        name="New tender Telegram notifications",
    )

    # ── Mock tender auto-notify every 5 minutes ───────────────────────────────
    scheduler.add_job(
        auto_notify_new_tenders,
        trigger=IntervalTrigger(minutes=5, timezone="Asia/Almaty"),
        id="auto_new_tender_notify",
        replace_existing=True,
        name="Auto new tender notifications",
    )

    active_jobs = ["daily_summary", "health_check",
                   "profitable_tender_alert", "new_tender_notifications",
                   "auto_new_tender_notify"]
    if not settings.DEV_MODE:
        active_jobs.insert(0, "hourly_tender_scan")

    logger.info(
        "Scheduler configured",
        dev_mode=settings.DEV_MODE,
        scan_interval_minutes=settings.SCAN_INTERVAL_MINUTES,
        jobs=active_jobs,
    )
    return scheduler


async def schedule_startup_scan(
    scheduler: AsyncIOScheduler,
    delay_seconds: int = 20,
) -> None:
    """
    Schedule a one-time scan shortly after startup for immediate fresh data.
    Runs `delay_seconds` after being called.
    """
    run_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
    scheduler.add_job(
        run_tender_scan,
        trigger="date",
        run_date=run_at,
        id="startup_scan",
        replace_existing=True,
        name="Startup scan",
    )
    logger.info(
        "Startup scan scheduled",
        in_seconds=delay_seconds,
        run_at=run_at.isoformat(),
    )
