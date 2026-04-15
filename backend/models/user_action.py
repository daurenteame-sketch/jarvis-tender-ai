from sqlalchemy import Column, Text, Numeric, String, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from core.database import Base


class UserAction(Base):
    __tablename__ = "user_actions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tender_id = Column(UUID(as_uuid=True), ForeignKey("tenders.id"), nullable=True)
    lot_id = Column(UUID(as_uuid=True), ForeignKey("tender_lots.id"), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    action = Column(String(50), nullable=False)  # viewed | ignored | bid_submitted | won | lost
    actual_bid_amount = Column(Numeric(18, 2))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    tender = relationship("Tender", back_populates="user_actions")
    lot = relationship("TenderLot", back_populates="user_actions")
    user = relationship("User", back_populates="actions")
