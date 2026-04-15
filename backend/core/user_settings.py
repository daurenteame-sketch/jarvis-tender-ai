"""
Per-user notification settings and tender filter.

Stored in /app/data/user_settings.json (Docker volume) or backend/data/ locally.
Each user identified by Telegram chat_id.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

# ── Storage path ───────────────────────────────────────────────────────────────

_DATA_DIR = Path("/app/data") if Path("/app/data").exists() or Path("/app").exists() \
    else Path(__file__).parent.parent / "data"
_SETTINGS_FILE = _DATA_DIR / "user_settings.json"


# ── Model ──────────────────────────────────────────────────────────────────────

@dataclass
class UserSettings:
    enabled: bool = True
    paused: bool = False                # ⏸ пауза — временно останавливает поток тендеров
    min_price: int = 1_000_000          # тг; 0 = не задан → ничего не отправлять
    keywords_include: list[str] = field(default_factory=list)   # [] = режим "только по цене"
    keywords_exclude: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    min_margin: float = 0.0             # percent
    max_per_hour: int = 10              # anti-spam cap


# ── CRUD ───────────────────────────────────────────────────────────────────────

def _load_all() -> dict:
    try:
        if _SETTINGS_FILE.exists():
            return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_all(data: dict) -> None:
    try:
        _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SETTINGS_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        print(f"❌ Failed to save user_settings: {exc}", flush=True)


def get_settings(chat_id: int | str) -> UserSettings:
    raw = _load_all().get(str(chat_id), {})
    s = UserSettings()
    for key, val in raw.items():
        if hasattr(s, key):
            setattr(s, key, val)
    return s


def save_settings(chat_id: int | str, s: UserSettings) -> None:
    data = _load_all()
    data[str(chat_id)] = asdict(s)
    _save_all(data)


def reset_settings(chat_id: int | str) -> UserSettings:
    s = UserSettings()
    save_settings(chat_id, s)
    return s


def is_configured(chat_id: int | str) -> bool:
    """
    Returns False only when min_price == 0 (filters explicitly cleared).
    Default state (min_price=1_000_000) is considered configured.
    """
    return get_settings(chat_id).min_price > 0


# ── Tender filter ──────────────────────────────────────────────────────────────

def filter_mode(chat_id: int | str) -> str:
    """Returns 'strict' if keywords set, 'price_only' otherwise."""
    s = get_settings(chat_id)
    return "strict" if s.keywords_include else "price_only"


def tender_matches(tender: dict, chat_id: int | str) -> bool:
    """
    Returns True if the tender passes the user's filter rules.

    Два режима:
      • «только по цене»  — keywords_include пустой: фильтр только по min_price
      • «строгий»         — keywords_include задан: price + совпадение хотя бы одного слова

    tender dict: {title, price, url, source, profitable?, margin_percent?}
    """
    s = get_settings(chat_id)

    # 1. Уведомления выключены или поток на паузе
    if not s.enabled or s.paused:
        return False

    # 2. min_price не задан (0) — не отправлять ничего
    if s.min_price <= 0:
        return False

    # 3. Минимальная цена
    if tender.get("price", 0) < s.min_price:
        return False

    title_lower = tender.get("title", "").lower()

    # 4. Строгий режим: должно совпасть хотя бы одно включённое слово
    if s.keywords_include:
        if not any(kw.lower() in title_lower for kw in s.keywords_include):
            return False

    # 5. Исключить тендеры с нежелательными словами
    if s.keywords_exclude:
        if any(kw.lower() in title_lower for kw in s.keywords_exclude):
            return False

    # 6. Минимальная маржа (0 = не фильтровать)
    margin = tender.get("margin_percent", 100.0)
    if margin < s.min_margin:
        return False

    return True


# ── Anti-spam ──────────────────────────────────────────────────────────────────

# { chat_id: [timestamp, timestamp, ...] }  — in-memory, resets on restart
_hourly_log: dict[str, list[float]] = {}


def can_send(chat_id: int | str) -> bool:
    """Rate-limit: returns False if user already received max_per_hour messages."""
    key = str(chat_id)
    s = get_settings(chat_id)
    now = time.time()
    window = 3600  # 1 hour

    timestamps = [t for t in _hourly_log.get(key, []) if now - t < window]
    _hourly_log[key] = timestamps

    if len(timestamps) >= s.max_per_hour:
        return False

    _hourly_log[key].append(now)
    return True


# ── Settings summary text ──────────────────────────────────────────────────────

def settings_text(chat_id: int | str) -> str:
    s = get_settings(chat_id)
    stream = "⏸ *ПАУЗА*" if s.paused else "▶️ *ВКЛ*"

    if s.min_price <= 0:
        price_str = "⚠️ *не задана* — уведомления остановлены"
        mode_str  = "🔴 *не настроен*"
    elif s.keywords_include:
        price_str = f"*{s.min_price:,.0f} тг*".replace(",", " ")
        mode_str  = "🔒 *Строгий* — цена + ключевые слова"
    else:
        price_str = f"*{s.min_price:,.0f} тг*".replace(",", " ")
        mode_str  = "💰 *Только по цене*"

    kw_in = "`" + ", ".join(s.keywords_include) + "`" if s.keywords_include else "_не заданы_"
    kw_ex = "`" + ", ".join(s.keywords_exclude) + "`" if s.keywords_exclude else "нет"

    return (
        f"⚙️ *Настройки уведомлений*\n"
        f"─────────────────────────\n"
        f"📡 Поток: {stream}\n"
        f"🎯 Режим: {mode_str}\n"
        f"💰 Мин. сумма: {price_str}\n"
        f"🔍 Включить слова: {kw_in}\n"
        f"❌ Исключить слова: {kw_ex}\n"
        f"📊 Мин. маржа: *{s.min_margin:.0f}%*\n"
        f"⏱ Макс. в час: *{s.max_per_hour}*"
    )
