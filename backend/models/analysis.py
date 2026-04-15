from sqlalchemy import Column, Text, Numeric, Boolean, String, JSON, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from core.database import Base


class TenderAnalysis(Base):
    __tablename__ = "tender_analyses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tender_id = Column(UUID(as_uuid=True), ForeignKey("tenders.id", ondelete="CASCADE"), nullable=False)
    product_name = Column(Text)
    brand_model = Column(Text)
    dimensions = Column(Text)
    technical_params = Column(JSON, default=dict)
    materials = Column(Text)
    quantity = Column(Numeric)
    unit = Column(String(50))
    analogs_allowed = Column(Boolean)
    spec_clarity = Column(String(20))   # clear | partial | vague
    extracted_specs = Column(JSON, default=dict)
    ai_summary = Column(Text)
    ai_model = Column(String(100))
    analyzed_at = Column(DateTime(timezone=True), server_default=func.now())

    tender = relationship("Tender", back_populates="analysis")
