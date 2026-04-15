"""
TenderLotAnalysis — AI-extracted specification data for a lot.
Separate from TenderAnalysis (which is for the parent tender).
"""
from sqlalchemy import Column, Integer, Text, Numeric, Boolean, String, JSON, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from core.database import Base


class TenderLotAnalysis(Base):
    __tablename__ = "tender_lot_analyses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lot_id = Column(UUID(as_uuid=True), ForeignKey("tender_lots.id", ondelete="CASCADE"), nullable=False)

    # AI-extracted product/service info
    product_name = Column(Text)
    product_name_en = Column(Text)
    brand = Column(Text)                # manufacturer / trade name
    brand_model = Column(Text)          # "Brand Model" combined, or model alone
    dimensions = Column(Text)
    technical_params = Column(JSON, default=dict)
    materials = Column(Text)
    quantity_extracted = Column(Numeric)
    unit_extracted = Column(String(100))
    analogs_allowed = Column(Boolean)
    spec_clarity = Column(String(20))   # clear | partial | vague
    key_requirements = Column(JSON, default=list)
    ai_summary_ru = Column(Text)
    is_software_related = Column(Boolean, default=False)
    software_type = Column(String(100))

    # Compact spec string extracted from ТЗ (e.g. "2х0,08–4мм², 32A, 400В")
    characteristics = Column(Text)

    # AI suggestion — inferred from spec characteristics (not verbatim from ТЗ)
    suggested_model       = Column(Text)             # AI-guessed model/type, null if unknown
    suggestion_confidence = Column(Integer)          # 0–100, null if not computed

    # Full AI response
    raw_ai_response = Column(JSON, default=dict)
    ai_model = Column(String(100))

    # Confidence of extraction
    extraction_confidence = Column(Numeric(3, 2))

    analyzed_at = Column(DateTime(timezone=True), server_default=func.now())

    lot = relationship("TenderLot", back_populates="analysis")
