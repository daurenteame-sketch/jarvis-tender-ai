"""
AI Specification Analyzer — uses GPT-4 to extract structured product/service info from tenders.
"""
import uuid
from typing import Optional
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import async_session_factory
from core.config import settings
from models.analysis import TenderAnalysis
from models.tender import Tender
from integrations.openai_client.client import OpenAIClient
from modules.ai_analyzer.category_classifier import CategoryClassifier

logger = structlog.get_logger(__name__)


class TenderAnalyzer:
    """Full AI-powered tender specification analyzer."""

    SOFTWARE_SERVICE_KEYWORDS = {
        "сайт", "веб-сайт", "веб сайт", "website",
        "портал", "portal", "web portal",
        "мобильное приложение", "mobile app", "мобильн",
        "программное обеспечение", "software", "по ",
        "информационная система", "information system", "ис ",
        "crm", "crm-система", "срм",
        "erp", "erp-система",
        "автоматизация", "automation",
        "платформа", "platform",
        "чат-бот", "chatbot", "бот",
        "искусственный интеллект", "ai system", "ии",
        "разработка системы", "разработка приложения",
        "цифровая платформа", "digital platform",
        "интеграция", "api", "микросервис",
    }

    def __init__(self):
        self.ai_client = OpenAIClient()
        self.classifier = CategoryClassifier()

    async def analyze(
        self,
        tender_id: uuid.UUID,
        title: str,
        description: str,
        spec_text: str,
        budget: float = 0,
    ) -> Optional[dict]:
        """
        Full analysis pipeline for a tender.
        Returns analysis dict or None if tender should be skipped.
        """
        # Step 1: Quick category classification (no AI, keyword-based)
        quick_category = self.classifier.classify_quick(title, description)

        # Step 2: If clearly "other" service, skip without API call
        if quick_category == "other":
            logger.debug("Tender skipped (other category)", title=title[:50])
            await self._save_category(tender_id, "other")
            return None

        # Step 3: Full AI analysis
        ai_result = await self.ai_client.analyze_tender_specification(
            title=title,
            description=description,
            spec_text=spec_text or description,
        )

        category = ai_result.get("category", quick_category)

        # Final category check
        if category == "other":
            await self._save_category(tender_id, "other")
            return None

        # Step 4: Save analysis to database
        analysis_data = {
            "tender_id": tender_id,
            "product_name": ai_result.get("product_name", title),
            "brand_model": ai_result.get("brand_model"),
            "dimensions": ai_result.get("dimensions"),
            "technical_params": ai_result.get("technical_params", {}),
            "materials": ai_result.get("materials"),
            "quantity": ai_result.get("quantity"),
            "unit": ai_result.get("unit", "шт"),
            "analogs_allowed": ai_result.get("analogs_allowed"),
            "spec_clarity": ai_result.get("spec_clarity", "vague"),
            "extracted_specs": ai_result,
            "ai_summary": ai_result.get("summary_ru", ""),
            "ai_model": settings.OPENAI_MODEL,
        }

        async with async_session_factory() as session:
            # Update tender category
            result = await session.execute(
                select(Tender).where(Tender.id == tender_id)
            )
            tender = result.scalar_one_or_none()
            if tender:
                tender.category = category
                await session.flush()

            # Save analysis
            analysis = TenderAnalysis(**analysis_data)
            session.add(analysis)
            await session.commit()

        logger.info(
            "Tender analyzed",
            tender_id=str(tender_id),
            category=category,
            product=analysis_data["product_name"][:50],
            spec_clarity=analysis_data["spec_clarity"],
        )

        return {**ai_result, "category": category, "tender_id": str(tender_id)}

    async def _save_category(self, tender_id: uuid.UUID, category: str):
        async with async_session_factory() as session:
            result = await session.execute(
                select(Tender).where(Tender.id == tender_id)
            )
            tender = result.scalar_one_or_none()
            if tender:
                tender.category = category
                await session.commit()
