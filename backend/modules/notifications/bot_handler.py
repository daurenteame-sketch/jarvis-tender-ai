"""
Telegram Bot Callback Handler — processes inline button presses from lot alerts.

Callback data patterns (set in telegram.py _build_lot_keyboard / _build_keyboard):
    action:bid_submitted:lot:{lot_id}  — "✅ Участвую"        → record action, confirm
    action:ignored:lot:{lot_id}        — "❌ Игнорировать"     → record action, confirm
    bid:lot:{lot_id}                   — "📄 Сгенерировать"    → generate DOCX, send file
    action:bid_submitted:{tender_id}   — tender-level participate
    action:ignored:{tender_id}         — tender-level ignore
    bid:{tender_id}                    — tender-level bid (DOCX not supported yet)
"""
from __future__ import annotations

import io
import re
import uuid

import structlog
from telegram import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from core.config import settings
from core.database import async_session_factory
from core.chat_id_store import save_chat_id, load_chat_id
from core.user_settings import get_settings, save_settings, reset_settings, settings_text, is_configured

logger = structlog.get_logger(__name__)

_stored = load_chat_id()
LAST_CHAT_ID: int | None = int(_stored) if _stored else None  # pre-load from file on startup

# ── Settings input state (multi-step dialog) ──────────────────────────────────
# chat_id → which field we're waiting for: "min_price"|"kw_in"|"kw_ex"|"margin"|"max_per_hour"
_pending_input: dict[int, str] = {}

# Default user until auth is implemented (matches lots.py hardcoded value)
_DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

_ACTION_REPLIES = {
    "bid_submitted": "✅ *Записано: вы участвуете в этом тендере*",
    "ignored":       "❌ *Записано: тендер проигнорирован*",
}


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _save_lot_action(lot_id: uuid.UUID, action: str, notes: str | None = None) -> bool:
    """Persist a UserAction for a lot. Returns True on success."""
    try:
        from sqlalchemy import select
        from models.tender_lot import TenderLot
        from models.user_action import UserAction

        async with async_session_factory() as session:
            row = await session.execute(select(TenderLot).where(TenderLot.id == lot_id))
            lot = row.scalar_one_or_none()
            if not lot:
                logger.warning("Lot not found for callback action", lot_id=str(lot_id))
                return False

            session.add(UserAction(
                lot_id=lot_id,
                tender_id=lot.tender_id,
                user_id=_DEFAULT_USER_ID,
                action=action,
                notes=notes,
            ))
            await session.commit()
            logger.info("Action saved via Telegram", lot_id=str(lot_id)[:8], action=action)
            return True

    except Exception as exc:
        logger.error("Failed to save lot action", error=str(exc))
        return False


async def _save_tender_action(tender_id: uuid.UUID, action: str) -> bool:
    """Persist a UserAction for a tender. Returns True on success."""
    try:
        from sqlalchemy import select
        from models.tender import Tender
        from models.user_action import UserAction

        async with async_session_factory() as session:
            row = await session.execute(select(Tender).where(Tender.id == tender_id))
            if not row.scalar_one_or_none():
                return False

            session.add(UserAction(
                tender_id=tender_id,
                user_id=_DEFAULT_USER_ID,
                action=action,
            ))
            await session.commit()
            return True

    except Exception as exc:
        logger.error("Failed to save tender action", error=str(exc))
        return False


async def _build_lot_bid(lot_id: uuid.UUID) -> tuple[bytes | None, str]:
    """
    Fetch lot data from DB and generate a DOCX bid proposal.
    Returns (docx_bytes, filename) on success, (None, error_message) on failure.
    """
    try:
        from sqlalchemy import select
        from models.tender import Tender
        from models.tender_lot import TenderLot
        from models.tender_lot_analysis import TenderLotAnalysis
        from models.profitability import ProfitabilityAnalysis
        from modules.bid_generator.generator import BidProposalGenerator

        async with async_session_factory() as session:
            lot_row = await session.execute(select(TenderLot).where(TenderLot.id == lot_id))
            lot = lot_row.scalar_one_or_none()
            if not lot:
                return None, "Лот не найден в базе данных"

            tender_row = await session.execute(select(Tender).where(Tender.id == lot.tender_id))
            tender = tender_row.scalar_one_or_none()

            analysis_row = await session.execute(
                select(TenderLotAnalysis).where(TenderLotAnalysis.lot_id == lot_id)
            )
            analysis = analysis_row.scalar_one_or_none()

            prof_row = await session.execute(
                select(ProfitabilityAnalysis).where(ProfitabilityAnalysis.lot_id == lot_id)
            )
            prof = prof_row.scalar_one_or_none()

        tender_data = {
            "title": lot.title or (tender.title if tender else ""),
            "platform": lot.platform,
            "budget": float(lot.budget) if lot.budget else 0,
            "deadline_at": str(lot.deadline_at) if lot.deadline_at else None,
            "customer_name": tender.customer_name if tender else "",
        }

        analysis_dict: dict = {}
        if analysis:
            analysis_dict = {
                "product_name_ru": analysis.product_name_ru,
                "brand_model": analysis.brand_model,
                "quantity": float(analysis.quantity_extracted) if analysis.quantity_extracted else None,
                "unit": analysis.unit,
                "spec_clarity": analysis.spec_clarity,
                "key_requirements": analysis.key_requirements or [],
                "ai_summary": analysis.ai_summary,
            }

        prof_dict: dict = {}
        if prof:
            prof_dict = {
                "total_cost": float(prof.total_cost) if prof.total_cost else 0,
                "expected_profit": float(prof.expected_profit) if prof.expected_profit else 0,
                "profit_margin_percent": float(prof.profit_margin_percent) if prof.profit_margin_percent else 0,
                "recommended_bid": float(prof.recommended_bid) if prof.recommended_bid else 0,
                "origin_country": prof.origin_country or "CN",
            }

        docx_bytes = await BidProposalGenerator().generate(
            tender_data=tender_data,
            analysis=analysis_dict,
            profitability=prof_dict,
        )
        filename = f"bid_{lot.lot_external_id or str(lot_id)[:8]}.docx"
        return docx_bytes, filename

    except Exception as exc:
        logger.error("Bid generation failed", lot_id=str(lot_id)[:8], error=str(exc))
        return None, f"Ошибка при генерации: {exc}"


# ── Callback router ───────────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route all inline-button callbacks to the correct handler."""
    query = update.callback_query
    # Acknowledge the press immediately — stops the Telegram loading spinner
    await query.answer()

    data: str = query.data or ""
    logger.info("Telegram callback", data=data[:60])

    # ── ✅ / ❌  lot-level action ─────────────────────────────────────────────
    if data.startswith("action:") and ":lot:" in data:
        # e.g. "action:bid_submitted:lot:550e8400-e29b-..."
        parts = data.split(":")  # ["action", "bid_submitted", "lot", "<uuid>"]
        if len(parts) != 4:
            return

        action, lot_id_str = parts[1], parts[3]
        try:
            lot_id = uuid.UUID(lot_id_str)
        except ValueError:
            await query.edit_message_reply_markup(reply_markup=None)
            return

        ok = await _save_lot_action(lot_id, action)
        reply_line = _ACTION_REPLIES.get(action, f"✅ Записано: {action}")

        if ok:
            # Remove keyboard and append a status line to the original message
            original = query.message.text or ""
            await query.edit_message_text(
                text=original + f"\n\n{reply_line}",
                parse_mode="Markdown",
                reply_markup=None,
            )
        return

    # ── ✅ / ❌  tender-level action ──────────────────────────────────────────
    if data.startswith("action:") and ":lot:" not in data:
        # e.g. "action:bid_submitted:550e8400-..."
        parts = data.split(":", 2)  # ["action", "bid_submitted", "<uuid>"]
        if len(parts) != 3:
            return

        action, tender_id_str = parts[1], parts[2]
        try:
            tender_id = uuid.UUID(tender_id_str)
        except ValueError:
            return

        ok = await _save_tender_action(tender_id, action)
        reply_line = _ACTION_REPLIES.get(action, f"✅ Записано: {action}")

        if ok:
            original = query.message.text or ""
            await query.edit_message_text(
                text=original + f"\n\n{reply_line}",
                parse_mode="Markdown",
                reply_markup=None,
            )
        return

    # ── 📄  generate DOCX for a lot ──────────────────────────────────────────
    if data.startswith("bid:lot:"):
        lot_id_str = data[len("bid:lot:"):]
        try:
            lot_id = uuid.UUID(lot_id_str)
        except ValueError:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ Неверный ID лота",
            )
            return

        # Remove keyboard, show progress
        await query.edit_message_reply_markup(reply_markup=None)
        progress_msg = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="⏳ Генерирую коммерческое предложение...",
        )

        docx_bytes, filename_or_err = await _build_lot_bid(lot_id)

        if docx_bytes:
            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=io.BytesIO(docx_bytes),
                filename=filename_or_err,
                caption="📄 *Коммерческое предложение готово*",
                parse_mode="Markdown",
            )
            # Also record as bid_submitted
            await _save_lot_action(lot_id, "bid_submitted", notes="telegram_bid_button")
            await progress_msg.delete()
        else:
            await progress_msg.edit_text(f"❌ {filename_or_err}")
        return

    # ── 📄  tender-level bid (no DOCX — redirect to dashboard) ───────────────
    if data.startswith("bid:") and not data.startswith("bid:lot:"):
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="📊 Откройте дашборд для генерации заявки по тендеру.",
        )
        return

    # ── ⚙️  Settings callbacks ────────────────────────────────────────────────
    if data.startswith("cfg:"):
        await _handle_settings_callback(query, context, data)
        return

    logger.warning("Unrecognised callback data", data=data[:80])


def _settings_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """Build the settings inline keyboard."""
    s = get_settings(chat_id)
    # Stream control: show the action the user CAN take (opposite of current state)
    stream_btn = (
        InlineKeyboardButton("⏸ Пауза",   callback_data="cfg:toggle")
        if not s.paused else
        InlineKeyboardButton("▶️ Старт",  callback_data="cfg:toggle")
    )
    return InlineKeyboardMarkup([
        [stream_btn],
        [
            InlineKeyboardButton("💰 Мин. сумма",    callback_data="cfg:min_price"),
            InlineKeyboardButton("📊 Мин. маржа %",  callback_data="cfg:margin"),
        ],
        [
            InlineKeyboardButton("🔍 Включить слова",  callback_data="cfg:kw_in"),
            InlineKeyboardButton("❌ Исключить слова", callback_data="cfg:kw_ex"),
        ],
        [
            InlineKeyboardButton("⏱ Макс в час",  callback_data="cfg:max_per_hour"),
            InlineKeyboardButton("🔄 Сброс",       callback_data="cfg:reset"),
        ],
    ])


async def _handle_settings_callback(query, context, data: str) -> None:
    """Handle all cfg: inline button presses."""
    chat_id = query.message.chat_id

    if data == "cfg:show":
        await context.bot.send_message(
            chat_id=chat_id,
            text=settings_text(chat_id),
            parse_mode="Markdown",
            reply_markup=_settings_keyboard(chat_id),
        )
        return

    if data == "cfg:toggle":
        s = get_settings(chat_id)
        s.paused = not s.paused
        save_settings(chat_id, s)
        status_line = "⏸ *Поток поставлен на паузу* — тендеры не отправляются." if s.paused \
                 else "▶️ *Поток запущен* — тендеры снова отправляются."
        await query.edit_message_text(
            text=f"{status_line}\n\n" + settings_text(chat_id),
            parse_mode="Markdown",
            reply_markup=_settings_keyboard(chat_id),
        )
        return

    if data == "cfg:reset":
        reset_settings(chat_id)
        await query.edit_message_text(
            text="✅ Настройки сброшены до умолчаний.\n\n" + settings_text(chat_id),
            parse_mode="Markdown",
            reply_markup=_settings_keyboard(chat_id),
        )
        return

    # For all other buttons — ask user to type a value (ForceReply highlights the input field)
    _PROMPTS: dict[str, tuple[str, str, str]] = {
        # key: (field_key, message_text, input_field_placeholder)
        "cfg:min_price": (
            "min_price",
            "💰 *Минимальная сумма тендера*\n\nВведите сумму в тенге.\n_Пример: 5 000 000_",
            "Например: 5000000",
        ),
        "cfg:margin": (
            "margin",
            "📊 *Минимальная маржа*\n\nВведите процент от 0 до 100.\n_Пример: 15_",
            "Например: 15",
        ),
        "cfg:kw_in": (
            "kw_in",
            "🔍 *Ключевые слова для включения*\n\nБот будет присылать ТОЛЬКО тендеры, в названии которых есть эти слова.\n\n_Введите через запятую:_\n_поставка, оборудование, мебель_\n\nОтправьте `-` чтобы очистить",
            "поставка, оборудование",
        ),
        "cfg:kw_ex": (
            "kw_ex",
            "❌ *Ключевые слова для исключения*\n\nТендеры с этими словами в названии бот будет пропускать.\n\n_Введите через запятую:_\n_аренда, консультация, услуги_\n\nОтправьте `-` чтобы очистить",
            "аренда, услуги",
        ),
        "cfg:max_per_hour": (
            "max_per_hour",
            "⏱ *Максимум сообщений в час*\n\nАнти-спам защита. Введите число от 1 до 100.\n_Пример: 5_",
            "Например: 5",
        ),
    }

    if data in _PROMPTS:
        field_key, prompt_text, placeholder = _PROMPTS[data]
        _pending_input[chat_id] = field_key
        await context.bot.send_message(
            chat_id=chat_id,
            text=prompt_text,
            parse_mode="Markdown",
            reply_markup=ForceReply(selective=True, input_field_placeholder=placeholder),
        )


async def _apply_pending_input(chat_id: int, text: str, context) -> bool:
    """
    If chat_id has a pending settings input, process it and return True.
    Returns False if no pending input (caller should continue normal handling).
    """
    field_key = _pending_input.pop(chat_id, None)
    if field_key is None:
        return False

    s = get_settings(chat_id)
    error = None

    try:
        if field_key == "min_price":
            s.min_price = int(text.replace(" ", "").replace(",", ""))
        elif field_key == "margin":
            s.min_margin = float(text.replace(",", "."))
        elif field_key == "max_per_hour":
            val = int(text)
            s.max_per_hour = max(1, min(val, 100))
        elif field_key == "kw_in":
            s.keywords_include = [] if text.strip() == "-" else [
                w.strip() for w in text.split(",") if w.strip()
            ]
        elif field_key == "kw_ex":
            s.keywords_exclude = [] if text.strip() == "-" else [
                w.strip() for w in text.split(",") if w.strip()
            ]
    except (ValueError, TypeError):
        error = "❌ Неверный формат. Попробуйте ещё раз."

    if error:
        await context.bot.send_message(chat_id=chat_id, text=error)
        return True

    save_settings(chat_id, s)

    # Build a specific confirmation line per field
    _confirmations: dict[str, str] = {
        "min_price":    f"💰 Мин. сумма: *{s.min_price:,.0f} тг*".replace(",", " "),
        "margin":       f"📊 Мин. маржа: *{s.min_margin:.0f}%*",
        "max_per_hour": f"⏱ Макс. в час: *{s.max_per_hour}*",
        "kw_in":  (
            f"🔍 Включить слова: `{', '.join(s.keywords_include)}`"
            if s.keywords_include else "🔍 Включить слова: _очищено (режим «только по цене»)_"
        ),
        "kw_ex": (
            f"❌ Исключить слова: `{', '.join(s.keywords_exclude)}`"
            if s.keywords_exclude else "❌ Исключить слова: _очищено_"
        ),
    }
    confirm_line = _confirmations.get(field_key, "✅ Сохранено")

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"✅ Сохранено: {confirm_line}\n\n" + settings_text(chat_id),
        parse_mode="Markdown",
        reply_markup=_settings_keyboard(chat_id),
    )
    return True


# ── Configure-filters prompt ──────────────────────────────────────────────────

async def send_configure_prompt(chat_id: int) -> None:
    """
    Send a one-time 'please configure your filters' message with [Open Settings] button.
    Called by the scheduler when min_price == 0 (filters explicitly cleared).
    """
    if not settings.TELEGRAM_BOT_TOKEN:
        return
    if is_configured(chat_id):
        return  # nothing to do

    from telegram import Bot
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("⚙️ Открыть настройки", callback_data="cfg:show"),
    ]])
    try:
        bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "⚠️ *Фильтры не настроены — уведомления остановлены*\n\n"
                "Укажи минимальную сумму тендера, чтобы бот снова начал присылать уведомления.\n\n"
                "💡 _По умолчанию бот работает в режиме «только по цене» от 1 000 000 тг. "
                "Добавь ключевые слова для строгой фильтрации._"
            ),
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    except Exception as exc:
        logger.warning("send_configure_prompt failed", chat_id=chat_id, error=str(exc))


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show current notification settings with inline control buttons."""
    chat_id = update.effective_chat.id
    await context.bot.send_message(
        chat_id=chat_id,
        text=settings_text(chat_id),
        parse_mode="Markdown",
        reply_markup=_settings_keyboard(chat_id),
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Welcome message with command list."""
    chat_id = update.effective_chat.id
    global LAST_CHAT_ID
    LAST_CHAT_ID = chat_id
    save_chat_id(chat_id)
    logger.info("incoming_chat_id", event_type="cmd_start", chat_id=chat_id)
    await context.bot.send_message(chat_id=chat_id, text=f"🔑 Твой CHAT_ID: `{chat_id}`", parse_mode="Markdown")
    from core.user_settings import filter_mode
    mode = filter_mode(chat_id)
    mode_hint = (
        "💰 Режим: *только по цене* (от 1 000 000 тг)\n"
        "_Добавь ключевые слова в /settings для строгой фильтрации._"
        if mode == "price_only" else
        "🔒 Режим: *строгий* — по цене + ключевым словам"
    ) if is_configured(chat_id) else (
        "⚠️ Фильтры не настроены — уведомления остановлены. Настрой через /settings."
    )

    text = (
        "🤖 *JARVIS — Тендерный ИИ-ассистент*\n"
        "─────────────────────────────\n"
        "Я анализирую тендеры Казахстана и нахожу прибыльные возможности.\n\n"
        f"{mode_hint}\n\n"
        "*Команды:*\n"
        "/settings — фильтры уведомлений\n"
        "/lots — топ прибыльных лотов\n"
        "/scan — запустить сканирование\n"
        "/stats — статистика платформы\n\n"
        "Или напишите поисковый запрос:\n"
        "_ноутбуки_, _медицинское оборудование_, _мебель_"
    )
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
    logger.info("cmd_start", chat_id=chat_id)


async def cmd_lots(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return top-5 profitable lots from DB."""
    chat_id = update.effective_chat.id
    try:
        from sqlalchemy import select, desc
        from models.tender_lot import TenderLot
        from models.profitability import ProfitabilityAnalysis

        async with async_session_factory() as session:
            rows = await session.execute(
                select(TenderLot, ProfitabilityAnalysis)
                .join(ProfitabilityAnalysis, ProfitabilityAnalysis.lot_id == TenderLot.id)
                .where(TenderLot.is_profitable == True)  # noqa: E712
                .order_by(desc(ProfitabilityAnalysis.profit_margin_percent))
                .limit(5)
            )
            results = rows.all()

        if not results:
            await context.bot.send_message(
                chat_id=chat_id,
                text="📭 Прибыльных лотов пока нет. Запустите /scan для обновления.",
            )
            return

        header = "🔥 *Топ прибыльных лотов:*\n─────────────────────────────\n"
        lines = []
        buttons = []
        for lot, prof in results:
            title = (lot.title or "Без названия")[:60]
            budget = f"{float(lot.budget):,.0f} ₸".replace(",", " ") if lot.budget else "—"
            margin = f"{float(prof.profit_margin_percent):.1f}%" if prof.profit_margin_percent else "—"
            conf_emoji = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(prof.confidence_level or "", "⚪")
            lines.append(f"{conf_emoji} *{title}*\n💰 {budget}  📈 {margin}\n")
            buttons.append([
                InlineKeyboardButton(
                    f"📊 {title[:30]}",
                    url=f"https://jarvis.alltame.kz/lots/{lot.id}",
                )
            ])

        await context.bot.send_message(
            chat_id=chat_id,
            text=header + "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        logger.info("cmd_lots sent", chat_id=chat_id, count=len(results))

    except Exception as exc:
        logger.error("cmd_lots failed", chat_id=chat_id, error=str(exc))
        await context.bot.send_message(chat_id=chat_id, text="❌ Ошибка при загрузке лотов.")


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Trigger a manual scan and report the result."""
    chat_id = update.effective_chat.id
    await context.bot.send_message(chat_id=chat_id, text="⏳ Запускаю сканирование...")
    logger.info("cmd_scan triggered", chat_id=chat_id)
    try:
        from modules.scanner.scanner import TenderScanner
        scanner = TenderScanner()
        stats = await scanner.run_scan_cycle()

        total_new = sum(s.get("tenders_new", 0) for s in stats.values() if isinstance(s, dict))
        total_profitable = sum(s.get("profitable_found", 0) for s in stats.values() if isinstance(s, dict))

        lines = ["✅ *Сканирование завершено*\n"]
        for platform, s in stats.items():
            if not isinstance(s, dict):
                continue
            lines.append(
                f"*{platform}:* найдено {s.get('tenders_found', 0)}, "
                f"новых {s.get('tenders_new', 0)}, "
                f"прибыльных {s.get('profitable_found', 0)}"
            )
        lines.append(f"\n🎯 Итого новых: {total_new} | Прибыльных: {total_profitable}")

        await context.bot.send_message(
            chat_id=chat_id, text="\n".join(lines), parse_mode="Markdown"
        )
    except Exception as exc:
        logger.error("cmd_scan failed", chat_id=chat_id, error=str(exc))
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Ошибка сканирования: {exc}")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send platform summary stats."""
    chat_id = update.effective_chat.id
    try:
        from sqlalchemy import select, func
        from models.tender_lot import TenderLot
        from models.profitability import ProfitabilityAnalysis
        from models.scan_run import ScanRun

        async with async_session_factory() as session:
            total_lots = (await session.execute(select(func.count(TenderLot.id)))).scalar() or 0
            profitable_lots = (
                await session.execute(
                    select(func.count(TenderLot.id)).where(TenderLot.is_profitable == True)  # noqa: E712
                )
            ).scalar() or 0
            avg_margin = (
                await session.execute(
                    select(func.avg(ProfitabilityAnalysis.profit_margin_percent))
                    .where(ProfitabilityAnalysis.is_profitable == True)  # noqa: E712
                )
            ).scalar()
            last_scan = (
                await session.execute(
                    select(ScanRun).order_by(ScanRun.completed_at.desc()).limit(1)
                )
            ).scalar_one_or_none()

        last_scan_str = (
            last_scan.completed_at.strftime("%d.%m %H:%M") if last_scan and last_scan.completed_at else "—"
        )
        text = (
            "📊 *Статистика JARVIS*\n"
            "─────────────────────────────\n"
            f"📦 Всего лотов: *{total_lots:,}*\n"
            f"✨ Прибыльных: *{profitable_lots:,}*\n"
            f"📈 Средняя маржа: *{float(avg_margin):.1f}%*\n"
            f"🕐 Последнее сканирование: *{last_scan_str}*\n\n"
            "Используйте /lots для просмотра возможностей."
        ).replace(",", " ")
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
        logger.info("cmd_stats sent", chat_id=chat_id)

    except Exception as exc:
        logger.error("cmd_stats failed", chat_id=chat_id, error=str(exc))
        await context.bot.send_message(chat_id=chat_id, text="❌ Ошибка при загрузке статистики.")


# ── Margin calculator ─────────────────────────────────────────────────────────

def _extract_numbers(text: str) -> list[float]:
    """
    Extract up to 3 numbers: [tender, cost, delivery].

    Handles:
    - Plain integers:           1000000 700000 50000
    - Space-thousands:          1 000 000  700 000  50 000
    - Keyword-prefixed:         тендер 1000000 закуп 700000 доставка 50000
    - Mixed order with keywords (reorders correctly)
    """
    _NUM = r'\d{1,3}(?:\s\d{3})+|\d+'

    def _parse(s: str) -> float:
        return float(s.replace(' ', ''))

    tl = text.lower()

    tender_m   = re.search(rf'(?:тендер[а-я]*|сумм[а-я]*)\D{{0,15}}({_NUM})', tl)
    cost_m     = re.search(rf'(?:закуп[а-я]*|себестоимост[а-я]*)\D{{0,15}}({_NUM})', tl)
    delivery_m = re.search(rf'(?:доставк[а-я]*|логистик[а-я]*|перевозк[а-я]*)\D{{0,15}}({_NUM})', tl)

    if tender_m and cost_m:
        try:
            result = [_parse(tender_m.group(1)), _parse(cost_m.group(1))]
            if delivery_m:
                result.append(_parse(delivery_m.group(1)))
            return result
        except ValueError:
            pass

    # Fallback: numbers in order of appearance
    result = []
    for token in re.findall(_NUM, text):
        try:
            result.append(_parse(token))
        except ValueError:
            pass
    return result


def _fmt(n: float) -> str:
    """Format number with spaces as thousands separator."""
    return f"{n:,.0f}".replace(",", " ")


def _build_margin_analysis(tender: float, cost: float, delivery: float = 0.0) -> str:
    if tender <= 0:
        return "❌ Сумма тендера должна быть больше нуля."

    margin     = tender - cost
    margin_pct = margin / tender * 100
    vat        = tender * 0.16
    net_profit = margin - vat - delivery
    net_pct    = net_profit / tender * 100

    delivery_line = f"Доставка: *{_fmt(delivery)} ₸*\n" if delivery > 0 else "Доставка: *не указана*\n"

    def _line(condition: bool, label: str) -> str:
        return f"*{label}*" if condition else label

    rec_go  = _line(net_profit > 0 and net_pct > 10,  "- >10% чистой прибыли → ЗАХОДИТЬ ✅")
    rec_mid = _line(net_profit > 0 and net_pct <= 10,  "- около 0% → ОСТОРОЖНО ⚠️")
    rec_no  = _line(net_profit <= 0,                   "- убыток → НЕ ЗАХОДИТЬ ❌")

    return (
        f"📊 *Анализ тендера:*\n"
        f"Сумма: *{_fmt(tender)} ₸*\n"
        f"Себестоимость: *{_fmt(cost)} ₸*\n"
        f"{delivery_line}"
        f"\n"
        f"💰 Маржа: *{_fmt(margin)} ₸*\n"
        f"📈 Рентабельность: *{margin_pct:.1f}%*\n"
        f"\n"
        f"🧾 НДС (16%): *{_fmt(vat)} ₸*\n"
        f"💸 Чистая прибыль: *{_fmt(net_profit)} ₸* ({net_pct:.1f}%)\n"
        f"\n"
        f"📌 *Рекомендация:*\n"
        f"{rec_go}\n"
        f"{rec_mid}\n"
        f"{rec_no}"
    )


# ── Text search handler ────────────────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id

    global LAST_CHAT_ID
    LAST_CHAT_ID = chat_id
    save_chat_id(chat_id)

    print(f"✅ SAVED CHAT_ID: {chat_id}", flush=True)

    query = update.message.text.strip()
    query_lower = query.lower()

    logger.info("incoming_chat_id", event_type="message", chat_id=chat_id)

    # ── SETTINGS INPUT — перехватываем ожидаемый ввод настроек ────────────────
    if await _apply_pending_input(chat_id, query, context):
        return

    # ── ПРИВЕТСТВИЕ — самый первый блок, до любой другой логики ───────────────
    if any(word in query_lower for word in ["привет", "hello", "hi"]):
        print(f"✅ GREETING MATCHED: '{query}' — OpenAI НЕ вызывается", flush=True)
        logger.info("handle_text greeting", chat_id=chat_id)
        await context.bot.send_message(
            chat_id=chat_id,
            text="Привет! Я AI ассистент Tele Scope 🚀"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text="🚀 бот запущен"
        )
        return

    logger.info("handle_text", chat_id=chat_id, query=query[:80])

    numbers = _extract_numbers(query)

    # 🔥 САМОЕ ВАЖНОЕ — если есть 2+ числа, считаем маржу и ВЫХОДИМ.
    # OpenAI и поиск по базе НИКОГДА не вызываются ниже этого блока.
    if len(numbers) >= 2:
        delivery = numbers[2] if len(numbers) >= 3 else 0.0
        text = _build_margin_analysis(numbers[0], numbers[1], delivery)
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
        return

    # ── "найди" — поиск на goszakup.gov.kz ────────────────────────────────────
    if query.lower().startswith("найди"):
        import asyncio
        from modules.tenders.search import search_tenders

        keyword = query[len("найди"):].strip()
        results = await asyncio.get_event_loop().run_in_executor(None, search_tenders, keyword)

        if not results:
            await context.bot.send_message(chat_id=chat_id, text="🔍 Ничего не найдено.")
            return

        tl = keyword.lower()

        if any(word in tl for word in ["выгод", "прибыль", "заход"]):
            results = [r for r in results if r.get("net_profit", 0) > 0]

        if "10 млн" in tl or "10000000" in tl:
            results = [r for r in results if r.get("price", 0) > 10000000]

        if not results:
            await context.bot.send_message(chat_id=chat_id, text="🔍 По вашим фильтрам ничего не найдено.")
            return

        lines = []
        for i, t in enumerate(results, 1):
            title  = t.get("title", "Без названия")
            url    = t.get("url", "")
            price  = t.get("price", 0)
            profit = t.get("net_profit", 0)
            nds    = t.get("nds", 0)

            rec = "ЗАХОДИТЬ ✅" if profit > 0 else "НЕ ЗАХОДИТЬ ❌"

            line  = f"*{i}. [{title}]({url})*\n"
            line += f"Сумма: {_fmt(price) if isinstance(price, (int, float)) else price} ₸\n"
            line += f"Маржа: {_fmt(profit)} ₸\n"
            line += f"НДС: {_fmt(nds)} ₸\n"
            line += f"Рекомендация: {rec}"

            lines.append(line)

        text = "🔍 *Найдено:*\n\n" + "\n\n---\n\n".join(lines)
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
        return

    # ── DB search (только если чисел < 2) ─────────────────────────────────────
    try:
        from sqlalchemy import select, desc, or_
        from models.tender_lot import TenderLot
        from models.profitability import ProfitabilityAnalysis

        async with async_session_factory() as session:
            rows = await session.execute(
                select(TenderLot, ProfitabilityAnalysis)
                .join(ProfitabilityAnalysis, ProfitabilityAnalysis.lot_id == TenderLot.id, isouter=True)
                .where(
                    or_(
                        TenderLot.title.ilike(f"%{query}%"),
                        TenderLot.technical_spec_text.ilike(f"%{query}%"),
                    )
                )
                .order_by(desc(TenderLot.is_profitable), desc(ProfitabilityAnalysis.profit_margin_percent))
                .limit(5)
            )
            results = rows.all()

        if not results:
            # ── 3. OpenAI fallback (only when DB empty AND no numbers) ─────────
            await context.bot.send_message(
                chat_id=chat_id,
                text="🤖 В базе тендеров ничего не найдено. Спрашиваю у ИИ...",
            )
            try:
                from integrations.openai_client.client import OpenAIClient
                ai_response = await OpenAIClient().ask_assistant(query)
                if ai_response:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"🤖 *Ответ ассистента:*\n\n{ai_response}",
                        parse_mode="Markdown",
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"🔍 По запросу «{query}» ничего не найдено.\n\nПопробуйте другой запрос или /scan для обновления базы.",
                    )
            except Exception as exc:
                logger.error("OpenAI fallback failed", chat_id=chat_id, error=str(exc))
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🔍 По запросу «{query}» ничего не найдено.\n\nПопробуйте другой запрос или /scan для обновления базы.",
                )
            return

        header = f"🔍 *Результаты по «{query}»:*\n─────────────────────────────\n"
        lines = []
        buttons = []
        for lot, prof in results:
            title = (lot.title or "Без названия")[:60]
            budget = f"{float(lot.budget):,.0f} ₸".replace(",", " ") if lot.budget else "—"
            margin_str = ""
            conf_emoji = "⚪"
            if prof and prof.profit_margin_percent:
                margin_str = f"  📈 {float(prof.profit_margin_percent):.1f}%"
                conf_emoji = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(prof.confidence_level or "", "⚪")
            lines.append(f"{conf_emoji} *{title}*\n💰 {budget}{margin_str}\n")
            buttons.append([
                InlineKeyboardButton(
                    f"📊 {title[:30]}",
                    url=f"https://jarvis.alltame.kz/lots/{lot.id}",
                )
            ])

        await context.bot.send_message(
            chat_id=chat_id,
            text=header + "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        logger.info("handle_text search replied", chat_id=chat_id, hits=len(results))

    except Exception as exc:
        logger.error("handle_text search failed", chat_id=chat_id, error=str(exc))
        await context.bot.send_message(chat_id=chat_id, text="❌ Ошибка при поиске.")


async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(
        "Telegram handler exception",
        update=str(update)[:200],
        error=str(context.error),
        exc_info=context.error,
    )


# ── Application factory ───────────────────────────────────────────────────────

def build_bot_application() -> Application:
    """
    Build and return a configured python-telegram-bot Application.
    Registers callback, command, and message handlers.
    Does NOT start polling — that is done in the FastAPI lifespan.
    """
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("lots",     cmd_lots))
    app.add_handler(CommandHandler("scan",     cmd_scan))
    app.add_handler(CommandHandler("stats",    cmd_stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(_error_handler)
    logger.info("Telegram bot application built")
    return app
