from sqlalchemy import Column, Text, Numeric, Integer, String, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from core.database import Base


class LogisticsEstimate(Base):
    __tablename__ = "logistics_estimates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lot_id = Column(UUID(as_uuid=True), ForeignKey("tender_lots.id", ondelete="CASCADE"), nullable=True)
    tender_id = Column(UUID(as_uuid=True), ForeignKey("tenders.id", ondelete="CASCADE"), nullable=True)
    origin_country = Column(String(50))
    shipping_cost = Column(Numeric(18, 2))
    customs_duty = Column(Numeric(18, 2))
    vat_amount = Column(Numeric(18, 2))
    total_logistics = Column(Numeric(18, 2))
    lead_time_days = Column(Integer)
    route = Column(Text)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    lot = relationship("TenderLot", foreign_keys=[lot_id])
