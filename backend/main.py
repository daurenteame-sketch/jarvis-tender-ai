"""
JARVIS Tender AI — FastAPI application entry point.
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.config import settings
from core.database import create_tables, check_db_connection
from core.logging import setup_logging
from api.routes import tenders, analytics, scan, lots, auth, users, procurement, suppliers as suppliers_router
from scheduler.tasks import create_scheduler, schedule_startup_scan

setup_logging()
logger = structlog.get_logger(__name__)


async def _seed_admin() -> None:
    """Ensure admin@tender.ai exists with role=admin. Create or update."""
    from sqlalchemy import select
    from core.database import async_session_factory
    from core.security import hash_password
    from models.company import Company
    from models.user import User

    ADMIN_EMAIL = "admin@tender.ai"
    ADMIN_PASSWORD = "admin123"

    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.email == ADMIN_EMAIL))
        user = result.scalar_one_or_none()

        if user:
            user.hashed_password = hash_password(ADMIN_PASSWORD)
            user.role = "admin"
            user.is_active = True
            await session.commit()
            logger.info("Admin user updated", email=ADMIN_EMAIL)
        else:
            # Get or create admin company
            result2 = await session.execute(select(Company).where(Company.name == "JARVIS Admin"))
            company = result2.scalar_one_or_none()
            if not company:
                company = Company(name="JARVIS Admin")
                session.add(company)
                await session.flush()

            admin = User(
                email=ADMIN_EMAIL,
                hashed_password=hash_password(ADMIN_PASSWORD),
                company_id=company.id,
                role="admin",
                is_active=True,
            )
            session.add(admin)
            await session.commit()
            logger.info("Admin user created", email=ADMIN_EMAIL)


async def _auto_discover_chat_id() -> None:
    """
    If chat_ids.json doesn't exist yet, call Telegram getUpdates to find
    the last user who wrote to the bot and save their chat_id.
    """
    from core.chat_id_store import load_chat_id, save_chat_id
    if load_chat_id():
        return  # already have it

    if not settings.TELEGRAM_BOT_TOKEN:
        return

    try:
        import httpx
        url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getUpdates"
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(url, params={"limit": 10, "offset": -10})
            data = resp.json()

        updates = data.get("result", [])
        for update in reversed(updates):
            msg = update.get("message") or update.get("callback_query", {}).get("message")
            if msg:
                chat_id = msg["chat"]["id"]
                save_chat_id(chat_id)
                print(f"✅ AUTO-DISCOVERED CHAT_ID: {chat_id}", flush=True)
                return

        print("⚠️  No Telegram updates found. Open your bot and send /start", flush=True)
    except Exception as exc:
        print(f"⚠️  Auto-discover chat_id failed: {exc}", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup → yield → shutdown."""
    logger.info("JARVIS starting", version=settings.APP_VERSION)

    # DB health check and table creation
    await check_db_connection()
    await create_tables()

    # Seed default admin user if none exists
    await _seed_admin()

    # Register pipeline steps (import triggers registration)
    _register_pipeline_steps()

    # Start scheduler
    scheduler = create_scheduler()
    scheduler.start()
    if settings.DEV_MODE:
        logger.info("DEV_MODE: startup scan skipped — trigger manually via POST /api/v1/scan/trigger")
    else:
        await schedule_startup_scan(scheduler, delay_seconds=20)

    # Auto-discover chat_id from Telegram getUpdates if not yet saved
    await _auto_discover_chat_id()

    # Send startup test notification to verify Telegram connectivity
    from scheduler.tasks import send_startup_test_notification
    await send_startup_test_notification()

    # Start Telegram bot polling (handles inline-button callbacks)
    bot_app = None
    if settings.TELEGRAM_BOT_TOKEN:
        try:
            from modules.notifications.bot_handler import build_bot_application
            bot_app = build_bot_application()
            await bot_app.initialize()
            await bot_app.start()
            await bot_app.updater.start_polling(
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query"],
            )
            logger.info("Telegram bot polling started")
        except Exception as exc:
            logger.warning("Telegram bot failed to start", error=str(exc))
            bot_app = None

    logger.info("JARVIS ready", docs_url="/api/docs")
    print("APP STARTED OK", flush=True)

    yield

    # Shutdown bot polling
    if bot_app:
        try:
            await bot_app.updater.stop()
            await bot_app.stop()
            await bot_app.shutdown()
            logger.info("Telegram bot stopped")
        except Exception as exc:
            logger.warning("Error stopping Telegram bot", error=str(exc))

    # Shutdown scheduler
    scheduler.shutdown(wait=False)
    logger.info("JARVIS shutdown")


def _register_pipeline_steps() -> None:
    """
    Register pipeline steps in execution order:
      1. ai_analysis   — classify lot + extract spec with GPT-4o
      2. profitability — supplier search, cost breakdown, margin calculation
      3. notification  — Telegram alert when lot is profitable

    Each step can set ctx.skip_remaining = True to short-circuit the chain
    (ai_analysis skips "other" lots before hitting the paid APIs).
    """
    from modules.scanner.pipeline import pipeline

    try:
        from modules.ai_analyzer.pipeline_step import register_ai_step
        register_ai_step(pipeline)
        logger.info("Pipeline step registered: ai_analysis")
    except Exception as exc:
        logger.warning("Could not register ai_analysis step", error=str(exc))

    try:
        from modules.profitability.pipeline_step import register_profitability_step
        register_profitability_step(pipeline)
        logger.info("Pipeline step registered: profitability")
    except Exception as exc:
        logger.warning("Could not register profitability step", error=str(exc))

    try:
        from modules.notifications.pipeline_step import register_notification_step
        register_notification_step(pipeline)
        logger.info("Pipeline step registered: notification")
    except Exception as exc:
        logger.warning("Could not register notification step", error=str(exc))


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI-powered tender intelligence platform for Kazakhstan",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(tenders.router, prefix="/api/v1")
app.include_router(lots.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")
app.include_router(scan.router, prefix="/api/v1")
app.include_router(procurement.router, prefix="/api/v1")
app.include_router(suppliers_router.router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/telegram/setup")
async def telegram_setup():
    """Диагностика Telegram: показывает текущий chat_id и отправляет тест."""
    from core.chat_id_store import load_chat_id, send_to_telegram

    stored_chat_id = load_chat_id()
    env_chat_id = settings.TELEGRAM_CHAT_ID
    active_chat_id = stored_chat_id or env_chat_id or None

    result = {
        "bot_token_set": bool(settings.TELEGRAM_BOT_TOKEN),
        "chat_id_from_file": stored_chat_id,
        "chat_id_from_env": env_chat_id,
        "active_chat_id": active_chat_id,
        "env_chat_id_is_placeholder": env_chat_id == "123456789",
    }

    if active_chat_id and active_chat_id != "123456789":
        ok = await send_to_telegram("✅ Тест: бот работает и отправляет сообщения!")
        result["test_message_sent"] = ok
    else:
        result["test_message_sent"] = False
        result["action_required"] = (
            "Откройте вашего бота в Telegram и отправьте /start — "
            "бот ответит вашим chat_id и сохранит его автоматически."
        )

    return result


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error("Unhandled exception", error=str(exc), path=str(request.url))
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

