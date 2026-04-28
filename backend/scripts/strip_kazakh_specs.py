"""One-shot cleanup: apply strip_kazakh_lines to every existing tender_lot row."""
import asyncio
from sqlalchemy import select

from core.database import async_session_factory
from models.tender_lot import TenderLot
from modules.parser.document_parser import strip_kazakh_lines


async def main() -> None:
    async with async_session_factory() as db:
        result = await db.execute(select(TenderLot))
        lots = result.scalars().all()
        changed = 0
        for lot in lots:
            for attr in ("technical_spec_text", "raw_spec_text"):
                val = getattr(lot, attr) or ""
                cleaned = strip_kazakh_lines(val)
                if cleaned != val:
                    setattr(lot, attr, cleaned)
                    changed += 1
        await db.commit()
        print(f"scanned {len(lots)} lots, updated {changed} fields")


if __name__ == "__main__":
    asyncio.run(main())
