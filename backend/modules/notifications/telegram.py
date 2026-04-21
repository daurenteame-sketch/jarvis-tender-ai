"""
Telegram Notification System — sends rich formatted alerts for profitable tenders.
"""
from datetime import datetime, timezone
from typing import Optional
import structlog
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from core.config import settings
from core.database import async_session_factory
from models.notification import Notification
from core.chat_id_store import load_chat_id

logger = structlog.get_logger(__name__)

PLATFORM_NAMES = {
    "goszakup": "🏛 GosZakup",
    "zakupsk": "🏢 Zakup SK",
}

CONFIDENCE_EMOJI = {
    "high": "🟢",
    "medium": "🟡",
    "low": "🔴",
}

CONFIDENCE_RU = {
    "high": "высокая",
    "medium": "средняя",
    "low": "низкая",
}

RISK_RU = {
    "low": "низкий",
    "medium": "средний",
    "high": "высокий",
}

COUNTRY_FLAGS = {
    "CN": "🇨🇳 Китай",
    "RU": "🇷🇺 Россия",
    "KZ": "🇰🇿 Казахстан",
}


class TelegramNotifier:
    def __init__(self):
        self._bot: Optional[Bot] = None

    def _get_bot(self) -> Bot:
        if not self._bot:
            self._bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
        return self._bot

    def _format_money(self, amount: float) -> str:
        return f"{amount:,.0f} ₸".replace(",", " ")

    def _format_deadline(self, deadline_at) -> str:
        if not deadline_at:
            return "не указано"
        if isinstance(deadline_at, str):
            try:
                deadline_at = datetime.fromisoformat(deadline_at.replace("Z", "+00:00"))
            except Exception:
                return deadline_at

        now = datetime.now(timezone.utc)
        if deadline_at.tzinfo is None:
            deadline_at = deadline_at.replace(tzinfo=timezone.utc)

        delta = deadline_at - now
        if delta.total_seconds() < 0:
            return "истёк"

        days = delta.days
        hours = delta.seconds // 3600

        parts = []
        if days > 0:
            parts.append(f"{days} дн.")
        if hours > 0:
            parts.append(f"{hours} ч.")
        return " ".join(parts) if parts else "менее часа"

    def _build_marketplace_lines(self, marketplace_links: list) -> str:
        """Build a short marketplace links block for Telegram messages."""
        if not marketplace_links:
            return ""
        country_groups: dict[str, list] = {"KZ": [], "RU": [], "CN": []}
        for link in marketplace_links:
            c = link.get("country", "CN")
            if c in country_groups:
                country_groups[c].append(link)

        flags = {"KZ": "🇰🇿", "RU": "🇷🇺", "CN": "🇨🇳"}
        lines = []
        for country, links in country_groups.items():
            if not links:
                continue
            # show max 2 per country
            for link in links[:2]:
                platform = link.get("platform", "")
                url = link.get("url", "")
                is_product = link.get("type") == "product"
                icon = "🟢" if is_product else "🔍"
                lines.append(f"{flags[country]} [{platform}]({url}) {icon}")
        return "\n".join(lines)

    def _build_message(self, tender_data: dict, profitability: dict, marketplace_links: list = None) -> str:
        platform = tender_data.get("platform", "")
        platform_name = PLATFORM_NAMES.get(platform, platform.upper())

        title = tender_data.get("title", "")
        if len(title) > 100:
            title = title[:97] + "..."

        budget = tender_data.get("budget", 0)
        product_cost = profitability.get("product_cost", 0)
        logistics_cost = profitability.get("logistics_cost", 0)
        customs_cost = profitability.get("customs_cost", 0)
        vat_amount = profitability.get("vat_amount", 0)
        operational = profitability.get("operational_costs", 0)
        total_cost = profitability.get("total_cost", 0)
        expected_profit = profitability.get("expected_profit", 0)
        margin = profitability.get("profit_margin_percent", 0)
        confidence = profitability.get("confidence_level", "medium")
        risk = profitability.get("risk_level", "medium")
        origin = profitability.get("origin_country", "CN")
        lead_time = profitability.get("lead_time_days", 30)

        confidence_emoji = CONFIDENCE_EMOJI.get(confidence, "🟡")
        confidence_ru = CONFIDENCE_RU.get(confidence, confidence)
        risk_ru = RISK_RU.get(risk, risk)
        origin_name = COUNTRY_FLAGS.get(origin, origin)

        deadline_str = self._format_deadline(tender_data.get("deadline_at"))

        # Recommendation logic
        if confidence == "high" and margin >= 60:
            recommendation = "✅ Рекомендуется участвовать"
        elif confidence == "high" and margin >= 50:
            recommendation = "✅ Можно участвовать"
        elif confidence == "medium" and margin >= 60:
            recommendation = "⚠️ Можно участвовать (проверьте поставщика)"
        else:
            recommendation = "⚠️ Участвовать с осторожностью"

        marketplace_block = ""
        if marketplace_links:
            ml_lines = self._build_marketplace_lines(marketplace_links)
            if ml_lines:
                marketplace_block = f"\n\n🛒 *Где купить товар:*\n{ml_lines}\n"

        message = (
            f"🎯 *Найден прибыльный тендер*\n"
            f"{'─' * 35}\n"
            f"📋 *Площадка:* {platform_name}\n"
            f"📦 *Предмет:* {title}\n"
            f"💰 *Сумма тендера:* {self._format_money(budget)}\n"
            f"\n"
            f"💹 *Финансовый анализ:*\n"
            f"├ Себестоимость товара: {self._format_money(product_cost)}\n"
            f"├ Логистика: {self._format_money(logistics_cost)}\n"
            f"├ Таможня: {self._format_money(customs_cost)}\n"
            f"├ НДС (12%): {self._format_money(vat_amount)}\n"
            f"├ Операционные расходы: {self._format_money(operational)}\n"
            f"└ *Итого затрат:* {self._format_money(total_cost)}\n"
            f"\n"
            f"✨ *Ожидаемая прибыль:* {self._format_money(expected_profit)}\n"
            f"📈 *Маржа:* {margin:.1f}%\n"
            f"\n"
            f"🚚 *Поставка:* {origin_name} · {lead_time} дней\n"
            f"⏰ *До окончания:* {deadline_str}\n"
            f"\n"
            f"🎯 *Уверенность:* {confidence_emoji} {confidence_ru}\n"
            f"⚠️ *Риск:* {risk_ru}"
            f"{marketplace_block}"
            f"\n{'─' * 35}\n"
            f"{recommendation}"
        )

        return message

    def _build_keyboard(self, tender_id: str, platform: str, external_id: str) -> InlineKeyboardMarkup:
        dashboard_url = f"https://jarvis.alltame.kz/tenders/{tender_id}"
        keyboard = [
            [
                InlineKeyboardButton("📊 Открыть детали", url=dashboard_url),
                InlineKeyboardButton("📄 Сгенерировать заявку", callback_data=f"bid:{tender_id}"),
            ],
            [
                InlineKeyboardButton("✅ Буду участвовать", callback_data=f"action:bid_submitted:{tender_id}"),
                InlineKeyboardButton("❌ Игнорировать", callback_data=f"action:ignored:{tender_id}"),
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    def _build_lot_keyboard(self, lot_id: str, tender_id: str, platform: str) -> InlineKeyboardMarkup:
        lot_url = f"https://jarvis.alltame.kz/lots/{lot_id}"
        keyboard = [
            [
                InlineKeyboardButton("📊 Открыть лот", url=lot_url),
                InlineKeyboardButton("📄 Сгенерировать заявку", callback_data=f"bid:lot:{lot_id}"),
            ],
            [
                InlineKeyboardButton("✅ Участвую", callback_data=f"action:bid_submitted:lot:{lot_id}"),
                InlineKeyboardButton("❌ Игнорировать", callback_data=f"action:ignored:lot:{lot_id}"),
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    async def send_lot_alert(
        self,
        tender_data: dict,
        lot_data: dict,
        lot_id: str,
        profitability: dict,
        chat_id: Optional[str] = None,
    ) -> bool:
        """
        Send Telegram notification for a profitable lot to a specific chat_id.
        Falls back to the globally stored chat_id when chat_id is not provided.
        Uses lot-level title and budget, falls back to tender values when absent.
        """
        target = chat_id or load_chat_id()
        if not settings.TELEGRAM_BOT_TOKEN or not target:
            logger.warning("Telegram not configured, skipping notification")
            return False

        try:
            # Merge: lot data overrides tender data for display
            merged = dict(tender_data)
            if lot_data.get("title"):
                merged["title"] = lot_data["title"]
            if lot_data.get("budget"):
                merged["budget"] = lot_data["budget"]
            if lot_data.get("deadline_at"):
                merged["deadline_at"] = lot_data["deadline_at"]

            # Generate marketplace links for the product (best effort, no timeout block)
            marketplace_links: list = []
            try:
                import asyncio as _asyncio
                from modules.supplier.product_search import get_product_links
                product_name = lot_data.get("title") or tender_data.get("title") or ""
                if product_name:
                    marketplace_links = await _asyncio.wait_for(
                        get_product_links(product_name=product_name, max_links=6),
                        timeout=5.0,
                    )
            except Exception:
                pass

            bot = self._get_bot()
            message = self._build_message(merged, profitability, marketplace_links=marketplace_links)
            tender_id = profitability.get("tender_id", "")
            keyboard = self._build_lot_keyboard(
                lot_id=lot_id,
                tender_id=tender_id,
                platform=tender_data.get("platform", ""),
            )

            await bot.send_message(
                chat_id=int(target),
                text=message,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard,
            )

            import uuid as uuid_mod
            async with async_session_factory() as session:
                notif = Notification(
                    tender_id=uuid_mod.UUID(tender_id) if tender_id else None,
                    lot_id=uuid_mod.UUID(lot_id) if lot_id else None,
                    channel="telegram",
                    recipient=str(target),
                    message=message,
                    status="sent",
                )
                session.add(notif)
                await session.commit()

            logger.info("Telegram lot alert sent", lot_id=lot_id[:8] if lot_id else None, chat_id=str(target)[-4:])
            return True

        except Exception as exc:
            logger.error("Failed to send Telegram lot alert", error=str(exc))
            return False

    async def send_to_all_matching_users(
        self,
        tender_data: dict,
        lot_data: dict,
        lot_id: str,
        profitability: dict,
    ) -> int:
        """
        Broadcast a profitable lot alert to ALL registered users whose filters match.
        Returns the number of users successfully notified.
        """
        from core.user_settings import get_all_chat_ids, tender_matches, can_send

        chat_ids = get_all_chat_ids()
        if not chat_ids:
            # Fallback: send to globally stored chat_id
            sent = await self.send_lot_alert(tender_data, lot_data, lot_id, profitability)
            return 1 if sent else 0

        # Build the tender dict for filter matching
        tender_filter_data = {
            "title":          lot_data.get("title") or tender_data.get("title", ""),
            "price":          float(lot_data.get("budget") or tender_data.get("budget") or 0),
            "margin_percent": float(profitability.get("profit_margin_percent") or 0),
            "category":       lot_data.get("category") or tender_data.get("category", ""),
        }

        notified = 0
        for cid in chat_ids:
            try:
                if not tender_matches(tender_filter_data, cid):
                    continue
                if not can_send(cid):
                    logger.debug("Rate limit hit, skipping", chat_id=str(cid)[-4:])
                    continue
                sent = await self.send_lot_alert(
                    tender_data, lot_data, lot_id, profitability, chat_id=cid
                )
                if sent:
                    notified += 1
            except Exception as exc:
                logger.error("Failed to notify user", chat_id=str(cid)[-4:], error=str(exc))

        logger.info("Broadcast complete", total_users=len(chat_ids), notified=notified)
        return notified

    async def send_tender_alert(
        self,
        tender_data: dict,
        profitability: dict,
    ) -> bool:
        """Send Telegram notification for a profitable tender."""
        if not settings.TELEGRAM_BOT_TOKEN or not load_chat_id():
            logger.warning("Telegram not configured, skipping notification")
            return False

        try:
            bot = self._get_bot()
            message = self._build_message(tender_data, profitability)
            tender_id = profitability.get("tender_id", "")
            keyboard = self._build_keyboard(
                tender_id=tender_id,
                platform=tender_data.get("platform", ""),
                external_id=tender_data.get("external_id", ""),
            )

            await bot.send_message(
                chat_id=load_chat_id(),
                text=message,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard,
            )

            # Save notification record
            async with async_session_factory() as session:
                notif = Notification(
                    tender_id=tender_id if tender_id else None,
                    channel="telegram",
                    recipient=str(load_chat_id()),
                    message=message,
                    status="sent",
                )
                session.add(notif)
                await session.commit()

            logger.info("Telegram notification sent", tender_id=tender_id)
            return True

        except Exception as e:
            logger.error("Failed to send Telegram notification", error=str(e))
            return False

    async def send_scan_summary(self, stats: dict):
        """Send daily/hourly scan summary."""
        if not settings.TELEGRAM_BOT_TOKEN or not load_chat_id():
            return

        try:
            bot = self._get_bot()
            total_found = sum(
                s.get("tenders_found", 0)
                for s in stats.values()
                if isinstance(s, dict)
            )
            total_profitable = sum(
                s.get("profitable_found", 0)
                for s in stats.values()
                if isinstance(s, dict)
            )

            message = (
                f"🤖 *JARVIS — Отчёт о сканировании*\n"
                f"📊 Найдено тендеров: {total_found}\n"
                f"✨ Прибыльных: {total_profitable}\n"
                f"⏰ Следующее сканирование через 1 час"
            )

            await bot.send_message(
                chat_id=load_chat_id(),
                text=message,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.error("Failed to send scan summary", error=str(e))

    async def send_message(self, text: str) -> None:
        """Send a plain Markdown message to the configured chat."""
        if not settings.TELEGRAM_BOT_TOKEN or not load_chat_id():
            return
        try:
            bot = self._get_bot()
            await bot.send_message(
                chat_id=load_chat_id(),
                text=text,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as exc:
            logger.error("Failed to send Telegram message", error=str(exc))

    async def send_error_alert(self, error_message: str):
        """Send error alert to Telegram."""
        if not settings.TELEGRAM_BOT_TOKEN or not load_chat_id():
            return
        try:
            bot = self._get_bot()
            await bot.send_message(
                chat_id=load_chat_id(),
                text=f"🚨 *JARVIS — Ошибка*\n\n`{error_message[:500]}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.error("Failed to send error alert", error=str(e))
