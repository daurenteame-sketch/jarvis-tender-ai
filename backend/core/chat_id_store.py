"""
Persistent chat_id storage + unified send_to_telegram().

Stores chat_id in /app/data/chat_ids.json — the Docker volume mount.
All outbound Telegram messages go through send_to_telegram().
"""
from __future__ import annotations

import json
from pathlib import Path

print("IMPORT FIXED OK", flush=True)

# Resolve storage path:
#   Docker:  /app/data/chat_ids.json  (docker-compose volume ./data:/app/data)
#   Local:   backend/data/chat_ids.json
_DATA_DIR = Path("/app/data") if Path("/app/data").exists() or Path("/app").exists() \
    else Path(__file__).parent.parent / "data"
_STORE_FILE = _DATA_DIR / "chat_ids.json"


def save_chat_id(chat_id: int | str) -> None:
    """Persist chat_id to disk. Overwrites previous value."""
    try:
        _STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STORE_FILE.write_text(json.dumps({"chat_id": str(chat_id)}), encoding="utf-8")
        print(f"✅ CHAT_ID SAVED TO FILE: {chat_id}", flush=True)
    except Exception as exc:
        print(f"❌ Failed to save chat_id: {exc}", flush=True)


def load_chat_id() -> str | None:
    """Load chat_id from disk. Returns None if file doesn't exist yet."""
    try:
        if _STORE_FILE.exists():
            data = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
            return data.get("chat_id")
    except Exception as exc:
        print(f"❌ Failed to load chat_id: {exc}", flush=True)
    return None


async def send_to_telegram(
    text: str,
    parse_mode: str = "Markdown",
    bypass_pause: bool = False,
) -> bool:
    """
    Single unified method for ALL outbound Telegram messages.

    chat_id priority:
      1. data/chat_ids.json  (saved when user writes to bot)
      2. TELEGRAM_CHAT_ID from .env  (fallback, always works)

    bypass_pause=True  — используется для системных сообщений (старт бота),
                         которые должны доходить независимо от паузы пользователя.
    """
    from core.config import settings
    from telegram import Bot

    chat_id = load_chat_id() or settings.TELEGRAM_CHAT_ID or None

    print(f"FINAL CHAT ID: {chat_id}", flush=True)

    if not chat_id:
        print("NO CHAT ID — set TELEGRAM_CHAT_ID in .env or send any message to the bot.", flush=True)
        return False

    if not settings.TELEGRAM_BOT_TOKEN:
        print("NO BOT TOKEN — set TELEGRAM_BOT_TOKEN in .env.", flush=True)
        return False

    # Respect pause setting (skip for system messages like startup notification)
    if not bypass_pause:
        try:
            from core.user_settings import get_settings
            if get_settings(chat_id).paused:
                print(f"⏸ PAUSED: tender notification blocked for chat_id {chat_id}", flush=True)
                return False
        except Exception:
            pass  # never block a message due to settings read failure

    try:
        bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
        await bot.send_message(
            chat_id=int(chat_id),
            text=text,
            parse_mode=parse_mode if parse_mode else None,
            disable_web_page_preview=True,
        )
        return True
    except Exception as exc:
        print(f"❌ send_to_telegram failed: {exc}", flush=True)
        return False
