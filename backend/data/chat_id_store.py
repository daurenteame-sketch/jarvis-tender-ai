"""
Persistent chat_id storage + single unified send_to_telegram() method.

ALL outbound Telegram messages MUST go through send_to_telegram().
chat_id is ALWAYS read from data/chat_ids.json — never from .env constants.
"""
from __future__ import annotations

import json
from pathlib import Path

print("IMPORT FIXED OK", flush=True)

_STORE_FILE = Path(__file__).parent / "chat_ids.json"


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


async def send_to_telegram(text: str, parse_mode: str = "Markdown") -> bool:
    """
    Single unified method for ALL outbound Telegram messages.

    - Always reads chat_id from data/chat_ids.json
    - Prints FINAL CHAT ID before every send
    - Logs NO CHAT ID and silently skips if file is missing
    - Never raises — logs error and returns False on failure
    """
    from core.config import settings
    from telegram import Bot

    chat_id = load_chat_id()

    print(f"FINAL CHAT ID: {chat_id}", flush=True)

    if not chat_id:
        print("NO CHAT ID — message not sent. Send any message to the bot first.", flush=True)
        return False

    if not settings.TELEGRAM_BOT_TOKEN:
        print("NO BOT TOKEN — message not sent.", flush=True)
        return False

    try:
        bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
        await bot.send_message(
            chat_id=int(chat_id),
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
        )
        return True
    except Exception as exc:
        print(f"❌ send_to_telegram failed: {exc}", flush=True)
        return False
