from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Optional
from functools import lru_cache

# Resolve .env path: works whether backend/ is the cwd or the project root is.
_ENV_FILE = next(
    (str(p) for p in [Path(".env"), Path("../.env")] if p.exists()),
    ".env",
)


class Settings(BaseSettings):
    # App
    APP_NAME: str = "JARVIS Tender AI"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    SECRET_KEY: str = "change-this-secret-key-in-production"
    ALLOWED_ORIGINS: str = "https://jarvis.alltame.kz,http://localhost:3000"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://jarvis:jarvis_password@postgres:5432/jarvis_db"
    DATABASE_URL_SYNC: str = "postgresql://jarvis:jarvis_password@postgres:5432/jarvis_db"

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"
    OPENAI_SEARCH_MODEL: str = "gpt-4o-search-preview"
    OPENAI_MAX_TOKENS: int = 4000

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # GosZakup API
    GOSZAKUP_API_TOKEN: str = ""
    GOSZAKUP_API_URL: str = "https://ows.goszakup.gov.kz/v2/graphql"
    GOSZAKUP_REST_URL: str = "https://goszakup.gov.kz/v3/public/api"

    # Zakup SK API
    ZAKUPSK_API_URL: str = "https://zakup.sk.kz"
    ZAKUPSK_API_TOKEN: str = ""

    # Exchange rates (2025 actual; override in .env)
    USD_TO_KZT: float = 487.0
    CNY_TO_KZT: float = 67.0
    RUB_TO_KZT: float = 5.2

    # Profitability thresholds
    # Kazakhstan government procurement: realistic supplier margins are 15-35%
    MIN_PROFIT_MARGIN: float = 15.0  # percent — minimum viable margin
    OPERATIONAL_COST_PERCENT: float = 3.0

    # Tax rates (Kazakhstan 2024–)
    VAT_RATE: float = 0.16  # 16% (raised from 12% in 2024)
    CUSTOMS_DUTY_CHINA: float = 0.05  # ~5% average
    CUSTOMS_DUTY_RUSSIA: float = 0.0  # EEU — no duty

    # Scan settings
    SCAN_INTERVAL_MINUTES: int = 60
    MAX_TENDERS_PER_SCAN: int = 500
    REQUEST_TIMEOUT: int = 30
    REQUEST_RETRY_COUNT: int = 3

    # Processing limit — caps how many tenders/lots are processed per run.
    # Applies to: scanning, margin recalculation, AI batch analysis.
    # Set to 0 to disable the cap (process everything).
    SCAN_LIMIT: int = 20

    # ── Development mode — cost controls ─────────────────────────────────────
    # Enables strict spending guards during development to prevent runaway costs.
    # Set DEV_MODE=false in production to lift all limits below.
    DEV_MODE: bool = True

    # Max lots per AI batch run (overrides mode limits when DEV_MODE=true)
    DEV_MAX_LOTS_PER_RUN: int = 20

    # Max OpenAI API calls per run (2 calls per lot: identify + analyze)
    DEV_MAX_OPENAI_REQUESTS_PER_RUN: int = 30

    # Soft budget limit: log a warning but continue
    DEV_BUDGET_SOFT_USD: float = 2.0

    # Hard budget limit: stop the run immediately
    DEV_BUDGET_HARD_USD: float = 3.0

    # Delay between OpenAI calls (seconds) to reduce rate-limit risk
    DEV_OPENAI_DELAY_S: float = 1.0

    # Confidence thresholds (lowered from 0.75/0.50 to reflect catalog-level accuracy)
    HIGH_CONFIDENCE_THRESHOLD: float = 0.70
    MEDIUM_CONFIDENCE_THRESHOLD: float = 0.45

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]

    class Config:
        env_file = _ENV_FILE
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    s = Settings()
    token = s.TELEGRAM_BOT_TOKEN
    chat_id = s.TELEGRAM_CHAT_ID
    print(f"[CONFIG] TELEGRAM_BOT_TOKEN: {'SET (ends: ...' + token[-6:] + ')' if token else 'EMPTY'}", flush=True)
    print(f"[CONFIG] TELEGRAM_CHAT_ID:   {chat_id if chat_id else 'EMPTY'}", flush=True)
    print(f"[CONFIG] env_file resolved:  {_ENV_FILE}", flush=True)
    return s


settings = get_settings()
