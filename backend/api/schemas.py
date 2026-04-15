"""
Pydantic schemas for API request/response validation.
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel
import uuid


# ---- Tender Schemas ----

class TenderBase(BaseModel):
    platform: str
    external_id: str
    status: str
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    budget: Optional[float] = None
    currency: str = "KZT"
    published_at: Optional[datetime] = None
    deadline_at: Optional[datetime] = None
    customer_name: Optional[str] = None


class TenderListItem(TenderBase):
    id: uuid.UUID
    first_seen_at: Optional[datetime] = None
    profit_margin: Optional[float] = None
    confidence_level: Optional[str] = None
    is_profitable: Optional[bool] = None

    class Config:
        from_attributes = True


class TenderDetail(TenderListItem):
    analysis: Optional[dict] = None
    profitability: Optional[dict] = None
    supplier_matches: Optional[list] = None
    logistics: Optional[dict] = None

    class Config:
        from_attributes = True


class TenderFilter(BaseModel):
    platform: Optional[str] = None
    category: Optional[str] = None
    is_profitable: Optional[bool] = None
    confidence_level: Optional[str] = None
    min_budget: Optional[float] = None
    max_budget: Optional[float] = None
    search: Optional[str] = None
    page: int = 1
    per_page: int = 20


# ---- Action Schemas ----

class UserActionCreate(BaseModel):
    tender_id: uuid.UUID
    action: str  # viewed | ignored | bid_submitted | won | lost
    actual_bid_amount: Optional[float] = None
    notes: Optional[str] = None


class UserActionResponse(BaseModel):
    id: uuid.UUID
    tender_id: uuid.UUID
    action: str
    created_at: datetime

    class Config:
        from_attributes = True


# ---- Analytics Schemas ----

class DashboardSummary(BaseModel):
    total_tenders: int
    profitable_tenders: int
    high_confidence: int
    avg_margin: float
    total_budget_scanned: float
    last_scan_at: Optional[datetime] = None
    tenders_today: int
    profitable_today: int


class ProfitTrend(BaseModel):
    date: str
    tenders_found: int
    profitable_found: int
    avg_margin: float


# ---- Scan Schemas ----

class ScanRunResponse(BaseModel):
    id: uuid.UUID
    platform: Optional[str]
    started_at: datetime
    completed_at: Optional[datetime]
    tenders_found: int
    tenders_new: int
    profitable_found: int
    status: str
    error_message: Optional[str]

    class Config:
        from_attributes = True


# ---- Auth Schemas ----

class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    company_name: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    is_active: bool
    company_id: Optional[uuid.UUID] = None
    company_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
