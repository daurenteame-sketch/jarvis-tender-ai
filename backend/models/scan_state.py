"""
ScanState — persists incremental scan position per platform.

Allows the scanner to resume from where it left off, avoiding
re-processing already-seen tenders on each hourly run.
"""
from sqlalchemy import Column, String, BigInteger, DateTime, JSON, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from core.database import Base


class ScanState(Base):
    __tablename__ = "scan_states"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform = Column(String(50), unique=True, nullable=False)

    # Last processed position (platform-specific)
    last_tender_id = Column(String(255))        # last external_id processed
    last_tender_int_id = Column(BigInteger)     # numeric ID for GosZakup offset
    last_scanned_page = Column(BigInteger, default=0)  # page offset for REST APIs

    # Timestamps
    last_scan_started_at = Column(DateTime(timezone=True))
    last_scan_completed_at = Column(DateTime(timezone=True))
    last_successful_scan_at = Column(DateTime(timezone=True))

    # Stats
    total_tenders_processed = Column(BigInteger, default=0)
    total_lots_processed = Column(BigInteger, default=0)
    total_profitable_found = Column(BigInteger, default=0)

    # Runtime state
    is_scanning = Column(Boolean, default=False)
    error_count = Column(BigInteger, default=0)
    last_error = Column(String(500))

    # Extra platform-specific state (e.g. cursors, tokens)
    extra = Column(JSON, default=dict)

    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
