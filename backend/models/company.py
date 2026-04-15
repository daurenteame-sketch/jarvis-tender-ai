from sqlalchemy import Column, String, Boolean, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from core.database import Base
from models.mixins import TimestampMixin


class Company(Base, TimestampMixin):
    __tablename__ = "companies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    subscription_plan = Column(String(50), default="basic")
    is_active = Column(Boolean, default=True)
    settings = Column(JSON, default=dict)

    users = relationship("User", back_populates="company")
