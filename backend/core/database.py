from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from core.config import settings
import structlog

logger = structlog.get_logger(__name__)

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=settings.DEBUG,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Idempotent column additions — safe to run on every startup.
        # ADD COLUMN IF NOT EXISTS is a no-op when the column already exists.
        for stmt in [
            "ALTER TABLE tender_lot_analyses ADD COLUMN IF NOT EXISTS suggested_model TEXT",
            "ALTER TABLE tender_lot_analyses ADD COLUMN IF NOT EXISTS suggestion_confidence INTEGER",
            "ALTER TABLE tender_lot_analyses ADD COLUMN IF NOT EXISTS characteristics TEXT",
            "ALTER TABLE tender_lot_analyses ADD COLUMN IF NOT EXISTS brand TEXT",
            "ALTER TABLE tender_lots ADD COLUMN IF NOT EXISTS raw_spec_text TEXT",
            "ALTER TABLE tender_lot_analyses ALTER COLUMN characteristics SET DEFAULT ''",
            "UPDATE tender_lot_analyses SET characteristics = '' WHERE characteristics IS NULL",
        ]:
            await conn.execute(text(stmt))
    logger.info("Database tables created / migrated successfully")


async def check_db_connection():
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("Database connection OK")
