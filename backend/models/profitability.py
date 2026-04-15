from sqlalchemy import Column, Numeric, Boolean, String, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from core.database import Base


class ProfitabilityAnalysis(Base):
    __tablename__ = "profitability_analyses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Primary link is to lot; tender_id kept for fallback
    lot_id = Column(UUID(as_uuid=True), ForeignKey("tender_lots.id", ondelete="CASCADE"), nullable=True)
    tender_id = Column(UUID(as_uuid=True), ForeignKey("tenders.id", ondelete="CASCADE"), nullable=True)

    product_cost = Column(Numeric(18, 2))
    logistics_cost = Column(Numeric(18, 2))
    customs_cost = Column(Numeric(18, 2))
    vat_amount = Column(Numeric(18, 2))
    operational_costs = Column(Numeric(18, 2))
    total_cost = Column(Numeric(18, 2))
    expected_profit = Column(Numeric(18, 2))
    profit_margin_percent = Column(Numeric(5, 2))
    is_profitable = Column(Boolean, default=False)
    confidence_level = Column(String(20))   # high | medium | low
    confidence_score = Column(Numeric(3, 2))
    recommended_bid = Column(Numeric(18, 2))
    safe_bid = Column(Numeric(18, 2))
    aggressive_bid = Column(Numeric(18, 2))
    risk_level = Column(String(20))         # low | medium | high
    origin_country = Column(String(10))     # CN | RU | KZ
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    lot = relationship("TenderLot", back_populates="profitability")
