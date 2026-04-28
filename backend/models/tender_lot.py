"""
TenderLot — individual lot within a tender announcement.

In Kazakhstan procurement:
  - A Tender (Announce) = umbrella procurement document
  - A Lot = the actual item/service being purchased (what suppliers bid on)

One tender can have many lots. Analysis pipeline runs at the lot level.
"""
from sqlalchemy import (
    Column, String, Text, Numeric, Integer, Boolean,
    DateTime, JSON, ForeignKey, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from core.database import Base


class TenderLot(Base):
    __tablename__ = "tender_lots"
    __table_args__ = (
        UniqueConstraint("platform", "lot_external_id", name="uq_lot_platform_external"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Parent tender
    tender_id = Column(UUID(as_uuid=True), ForeignKey("tenders.id", ondelete="CASCADE"), nullable=False)

    # Platform identity
    platform = Column(String(50), nullable=False)        # goszakup | zakupsk
    lot_external_id = Column(String(255), nullable=False) # platform lot ID

    # Core fields
    lot_number = Column(Integer)                          # lot number within tender
    title = Column(Text, nullable=False)
    description = Column(Text)
    technical_spec_text = Column(Text)                    # AI-ready spec text (≤10 000 chars)
    raw_spec_text = Column(Text)                          # full untruncated extracted text (debug)
    techspec_pdf_url = Column(Text)                       # direct URL to the techspec PDF on goszakup

    # Product/service details
    quantity = Column(Numeric(18, 4))
    unit = Column(String(100))                            # pieces, kg, m2, hours, etc.
    budget = Column(Numeric(18, 2))
    currency = Column(String(10), default="KZT")

    # Category (set by AI classifier)
    category = Column(String(50))   # product | software_service | other | unknown

    # Status & dates
    status = Column(String(50), default="published")
    deadline_at = Column(DateTime(timezone=True))

    # Documents attached to this lot
    documents = Column(JSON, default=list)                # [{url, name, type}]

    # Raw data from platform
    raw_data = Column(JSON, default=dict)

    # Processing state
    is_analyzed = Column(Boolean, default=False)
    is_profitable = Column(Boolean, default=None)
    confidence_level = Column(String(20))                 # high | medium | low
    profit_margin_percent = Column(Numeric(5, 2))
    notification_sent = Column(Boolean, default=False)

    first_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    tender = relationship("Tender", back_populates="lots")
    analysis = relationship("TenderLotAnalysis", back_populates="lot", uselist=False)
    supplier_matches = relationship("SupplierMatch", back_populates="lot")
    profitability = relationship("ProfitabilityAnalysis", back_populates="lot", uselist=False)
    notifications = relationship("Notification", back_populates="lot")
    user_actions = relationship("UserAction", back_populates="lot")
