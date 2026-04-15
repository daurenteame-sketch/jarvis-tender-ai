from sqlalchemy import Column, String, Boolean, BigInteger, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from core.database import Base
from models.mixins import TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True)
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255))
    telegram_chat_id = Column(BigInteger, nullable=True)
    role = Column(String(50), default="user")
    is_active = Column(Boolean, default=True)

    company = relationship("Company", back_populates="users")
    actions = relationship("UserAction", back_populates="user")
