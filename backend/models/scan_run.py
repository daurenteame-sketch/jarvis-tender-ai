from sqlalchemy import Column, Text, Integer, String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
from core.database import Base


class ScanRun(Base):
    __tablename__ = "scan_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform = Column(String(50))
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))
    tenders_found = Column(Integer, default=0)
    tenders_new = Column(Integer, default=0)
    profitable_found = Column(Integer, default=0)
    status = Column(String(50), default="running")  # running | completed | failed
    error_message = Column(Text)
