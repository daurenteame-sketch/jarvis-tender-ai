from sqlalchemy import Column, Text, Numeric, Boolean, String, JSON, Integer, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from core.database import Base
from models.mixins import TimestampMixin


class Supplier(Base, TimestampMixin):
    __tablename__ = "suppliers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    country = Column(String(50))
    source = Column(String(100))
    contact_info = Column(JSON, default=dict)
    rating = Column(Numeric(3, 2))
    verified = Column(Boolean, default=False)

    matches = relationship("SupplierMatch", back_populates="supplier")


class SupplierMatch(Base):
    __tablename__ = "supplier_matches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lot_id = Column(UUID(as_uuid=True), ForeignKey("tender_lots.id", ondelete="CASCADE"), nullable=True)
    tender_id = Column(UUID(as_uuid=True), ForeignKey("tenders.id", ondelete="CASCADE"), nullable=True)
    supplier_id = Column(UUID(as_uuid=True), ForeignKey("suppliers.id"))
    product_name = Column(Text)
    unit_price = Column(Numeric(18, 2))
    currency = Column(String(10), default="USD")
    unit_price_kzt = Column(Numeric(18, 2))
    moq = Column(Integer)
    lead_time_days = Column(Integer)
    match_score = Column(Numeric(3, 2))
    source_url = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    lot = relationship("TenderLot", back_populates="supplier_matches")
    supplier = relationship("Supplier", back_populates="matches")
