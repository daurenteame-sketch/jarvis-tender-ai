from sqlalchemy import Column, Text, String, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from core.database import Base


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tender_id = Column(UUID(as_uuid=True), ForeignKey("tenders.id"), nullable=True)
    lot_id = Column(UUID(as_uuid=True), ForeignKey("tender_lots.id"), nullable=True)
    channel = Column(String(50), default="telegram")
    recipient = Column(String(255))
    message = Column(Text)
    sent_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String(50), default="sent")

    tender = relationship("Tender", back_populates="notifications")
    lot = relationship("TenderLot", back_populates="notifications")
