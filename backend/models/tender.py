from sqlalchemy import Column, String, Text, Numeric, DateTime, JSON, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from core.database import Base
from models.mixins import TimestampMixin


class Tender(Base, TimestampMixin):
    __tablename__ = "tenders"
    __table_args__ = (UniqueConstraint("platform", "external_id", name="uq_tender_platform_external"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform = Column(String(50), nullable=False)        # goszakup | zakupsk
    external_id = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False)          # published | closed | cancelled

    # Announcement-level fields
    title = Column(Text, nullable=False)
    description = Column(Text)
    procurement_method = Column(String(100))             # open_tender, single_source, etc.

    # Financial
    budget = Column(Numeric(18, 2))                      # total budget (sum of lots)
    currency = Column(String(10), default="KZT")

    # Customer
    customer_name = Column(Text)
    customer_bin = Column(String(20))                    # БИН организации
    customer_region = Column(String(100))

    # Dates
    published_at = Column(DateTime(timezone=True))
    deadline_at = Column(DateTime(timezone=True))        # tender closing date

    # Category (set after lot analysis)
    category = Column(String(100))                       # product | software_service | mixed | other

    # Raw & documents
    raw_data = Column(JSON, default=dict)
    documents = Column(JSON, default=list)               # announcement-level docs

    # Scanner metadata
    first_seen_at = Column(DateTime(timezone=True))

    # Relationships
    lots = relationship("TenderLot", back_populates="tender", cascade="all, delete-orphan")
    analysis = relationship("TenderAnalysis", back_populates="tender", uselist=False)
    notifications = relationship("Notification", back_populates="tender")
    user_actions = relationship("UserAction", back_populates="tender")
