# JARVIS Tender Intelligence System — Master Specification

**Version:** 1.0.0
**Date:** 2026-03-11
**Classification:** Internal Engineering Document

---

## 1. System Overview

JARVIS (Just A Rather Very Intelligent System) is an AI-powered tender intelligence platform designed to automatically discover, analyze, and evaluate government procurement tenders on Kazakhstani platforms. The system identifies profitable opportunities, estimates margins, discovers suppliers, and delivers actionable insights via Telegram and a web dashboard.

### 1.1 Business Goals

- Automatically scan tender platforms every hour
- Detect tenders with profit margin ≥ 50%
- Analyze tender specifications using AI
- Find matching suppliers (Kazakhstan, Russia, China)
- Calculate full cost structure including logistics and taxes
- Alert user via Telegram with ready-to-act analysis
- Generate draft bid proposals automatically
- Learn from historical data to improve predictions

### 1.2 Target Platforms

| Platform | URL | Type |
|----------|-----|------|
| GosZakup | https://goszakup.gov.kz | Government procurement |
| Zakup SK | https://zakup.sk.kz | Samruk-Kazyna procurement |

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         JARVIS PLATFORM                         │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │   Scheduler  │───▶│    Scanner   │───▶│     Parser       │  │
│  │  (APScheduler│    │  GosZakup +  │    │  PDF/DOC/HTML    │  │
│  │   1hr cycle) │    │   Zakup SK   │    │  Extraction      │  │
│  └──────────────┘    └──────────────┘    └────────┬─────────┘  │
│                                                   │             │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    AI PIPELINE                           │  │
│  │  ┌────────────┐  ┌─────────────┐  ┌──────────────────┐  │  │
│  │  │  Spec AI   │  │  Supplier   │  │   Profitability  │  │  │
│  │  │  Analyzer  │  │  Discovery  │  │     Engine       │  │  │
│  │  │  (OpenAI)  │  │  (Search)   │  │  (Cost+Margin)   │  │  │
│  │  └────────────┘  └─────────────┘  └──────────────────┘  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                             │                                   │
│  ┌──────────────┐    ┌──────▼───────┐    ┌──────────────────┐  │
│  │   Telegram   │◀───│  Confidence  │───▶│  Bid Generator   │  │
│  │ Notification │    │   Scorer     │    │  (Draft Proposal)│  │
│  └──────────────┘    └──────────────┘    └──────────────────┘  │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              PostgreSQL Database                         │   │
│  │  tenders | analyses | suppliers | logistics | actions   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              Web Dashboard (Next.js)                     │   │
│  │  Tender List | Analytics | Suppliers | CRM | History    │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Data Flow

```
1. APScheduler triggers scan every 60 minutes
2. Scanner fetches published tenders via platform APIs
3. Deduplication check against PostgreSQL
4. New tenders → Parser extracts title, description, budget, deadline
5. Document downloader fetches attached PDF/DOC files
6. AI Spec Analyzer (GPT-4) reads specifications, extracts parameters
7. Category classifier: product tender OR qualifying service tender
8. Supplier Discovery searches Alibaba / Russian suppliers / local catalogs
9. Logistics Estimator calculates shipping cost (China/Russia/KZ → KZ)
10. Profitability Engine: total_cost = product + logistics + customs + VAT + ops
11. profit_margin = (budget - total_cost) / budget * 100
12. If margin >= 50%: proceed to confidence scoring
13. Confidence Scorer evaluates spec clarity, supplier match, logistics
14. If confidence = High or Medium: send Telegram notification
15. Bid Generator creates draft proposal document
16. All data stored in PostgreSQL for learning & dashboard
17. Web Dashboard shows full analysis in real-time
```

---

## 4. Database Schema

### 4.1 Core Tables

```sql
-- Companies (SaaS multi-tenancy)
CREATE TABLE companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    subscription_plan VARCHAR(50) DEFAULT 'basic',
    is_active BOOLEAN DEFAULT TRUE,
    settings JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Users
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES companies(id),
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255),
    telegram_chat_id BIGINT,
    role VARCHAR(50) DEFAULT 'user',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tenders
CREATE TABLE tenders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform VARCHAR(50) NOT NULL,         -- 'goszakup' | 'zakupsk'
    external_id VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL,           -- 'published' | 'closed' | 'cancelled'
    title TEXT NOT NULL,
    description TEXT,
    category VARCHAR(100),                  -- 'product' | 'software_service' | 'other'
    budget NUMERIC(18,2),
    currency VARCHAR(10) DEFAULT 'KZT',
    published_at TIMESTAMPTZ,
    deadline_at TIMESTAMPTZ,
    customer_name TEXT,
    customer_bin VARCHAR(20),
    raw_data JSONB,
    documents JSONB DEFAULT '[]',
    first_seen_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(platform, external_id)
);

-- AI Analyses
CREATE TABLE tender_analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tender_id UUID REFERENCES tenders(id) ON DELETE CASCADE,
    product_name TEXT,
    brand_model TEXT,
    dimensions TEXT,
    technical_params JSONB DEFAULT '{}',
    materials TEXT,
    quantity NUMERIC,
    unit VARCHAR(50),
    analogs_allowed BOOLEAN,
    spec_clarity VARCHAR(20),              -- 'clear' | 'partial' | 'vague'
    extracted_specs JSONB DEFAULT '{}',
    ai_summary TEXT,
    ai_model VARCHAR(100),
    analyzed_at TIMESTAMPTZ DEFAULT NOW()
);

-- Suppliers
CREATE TABLE suppliers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    country VARCHAR(50),                   -- 'CN' | 'RU' | 'KZ'
    source VARCHAR(100),                   -- 'alibaba' | 'russian_alibaba' | 'local'
    contact_info JSONB DEFAULT '{}',
    rating NUMERIC(3,2),
    verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Supplier Matches
CREATE TABLE supplier_matches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tender_id UUID REFERENCES tenders(id) ON DELETE CASCADE,
    supplier_id UUID REFERENCES suppliers(id),
    product_name TEXT,
    unit_price NUMERIC(18,2),
    currency VARCHAR(10) DEFAULT 'USD',
    unit_price_kzt NUMERIC(18,2),
    moq INTEGER,
    lead_time_days INTEGER,
    match_score NUMERIC(3,2),
    source_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Logistics Estimates
CREATE TABLE logistics_estimates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tender_id UUID REFERENCES tenders(id) ON DELETE CASCADE,
    origin_country VARCHAR(50),
    shipping_cost NUMERIC(18,2),
    customs_duty NUMERIC(18,2),
    vat_amount NUMERIC(18,2),
    total_logistics NUMERIC(18,2),
    lead_time_days INTEGER,
    route TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Profitability Analyses
CREATE TABLE profitability_analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tender_id UUID REFERENCES tenders(id) ON DELETE CASCADE,
    product_cost NUMERIC(18,2),
    logistics_cost NUMERIC(18,2),
    customs_cost NUMERIC(18,2),
    vat_amount NUMERIC(18,2),
    operational_costs NUMERIC(18,2),
    total_cost NUMERIC(18,2),
    expected_profit NUMERIC(18,2),
    profit_margin_percent NUMERIC(5,2),
    is_profitable BOOLEAN,
    confidence_level VARCHAR(20),          -- 'high' | 'medium' | 'low'
    confidence_score NUMERIC(3,2),
    recommended_bid NUMERIC(18,2),
    safe_bid NUMERIC(18,2),
    aggressive_bid NUMERIC(18,2),
    risk_level VARCHAR(20),                -- 'low' | 'medium' | 'high'
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Notifications
CREATE TABLE notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tender_id UUID REFERENCES tenders(id),
    channel VARCHAR(50) DEFAULT 'telegram',
    recipient VARCHAR(255),
    message TEXT,
    sent_at TIMESTAMPTZ DEFAULT NOW(),
    status VARCHAR(50) DEFAULT 'sent'
);

-- User Actions (Self-learning)
CREATE TABLE user_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tender_id UUID REFERENCES tenders(id),
    user_id UUID REFERENCES users(id),
    action VARCHAR(50),                    -- 'viewed' | 'ignored' | 'bid_submitted' | 'won' | 'lost'
    actual_bid_amount NUMERIC(18,2),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Scan History
CREATE TABLE scan_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform VARCHAR(50),
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    tenders_found INTEGER DEFAULT 0,
    tenders_new INTEGER DEFAULT 0,
    profitable_found INTEGER DEFAULT 0,
    status VARCHAR(50) DEFAULT 'running',
    error_message TEXT
);
```

---

## 5. Module Descriptions

### 5.1 Scanner Module
- Connects to GosZakup GraphQL API and Zakup SK REST API
- Fetches tenders with status = "published"
- Implements incremental scanning (tracks last_scanned_id per platform)
- Deduplicates via (platform, external_id) unique constraint
- Rate limiting: max 10 req/sec per platform

### 5.2 Parser Module
- Extracts structured data from tender HTML/JSON responses
- Downloads attached documents (PDF, DOCX)
- Uses pdfplumber + python-docx for text extraction
- Handles encoding issues for Cyrillic text

### 5.3 AI Specification Analyzer
- Uses GPT-4 to read technical specifications
- Extracts: product name, brand, model, dimensions, materials, params
- Determines if analog products are allowed
- Returns structured JSON + confidence score
- Prompt engineering in English, specs in any language

### 5.4 Category Classifier
- Products: ALL categories qualify
- Services: only IT/software categories qualify (whitelist-based)
- Uses keyword matching + AI classification for edge cases

### 5.5 Supplier Discovery Engine
- Searches Alibaba API / scraping for product matches
- Searches Russian supplier directories
- Queries local Kazakhstan supplier database
- Returns: supplier name, price, MOQ, lead time, match score

### 5.6 Logistics & Tax Estimator
- Routes: CN→KZ, RU→KZ, KZ local
- Customs duty rates by HS code category
- VAT: 12% Kazakhstan standard rate
- Shipping cost estimation by weight/volume/distance

### 5.7 Profitability Engine
- total_cost = product_cost + logistics + customs + VAT + operational
- operational_costs = 3% of budget (default)
- profit_margin = (budget - total_cost) / budget * 100
- Only triggers notification if margin >= 50%

### 5.8 Confidence Scorer
- Weights: spec_clarity(30%) + supplier_match(30%) + logistics_reliability(20%) + price_accuracy(20%)
- High: score >= 0.75
- Medium: score >= 0.50
- Low: score < 0.50

### 5.9 Telegram Notification System
- Rate limited: max 1 message per tender per day
- Rich formatted messages with all financial data
- Inline keyboard buttons: View Details | Generate Bid | Ignore
- Stores all sent notifications in DB

### 5.10 Bid Proposal Generator
- Template-based DOCX generation using python-docx
- Fills in: company details, technical compliance, pricing table
- Outputs formatted proposal ready for submission

### 5.11 Self-Learning System
- Tracks user actions on each tender
- Won/Lost feedback adjusts confidence model weights
- Recalibrates profitability estimates based on actual outcomes

---

## 6. API Endpoints

```
GET  /api/v1/tenders              — List tenders (paginated, filtered)
GET  /api/v1/tenders/{id}         — Tender detail with full analysis
POST /api/v1/tenders/{id}/action  — Record user action
GET  /api/v1/tenders/{id}/bid     — Generate bid proposal (DOCX)
GET  /api/v1/analytics/summary    — Dashboard summary stats
GET  /api/v1/analytics/trends     — Profit trends over time
GET  /api/v1/suppliers            — Supplier database
POST /api/v1/scan/trigger         — Manually trigger scan
GET  /api/v1/scan/history         — Scan run history
GET  /health                      — Health check
```

---

## 7. Deployment Architecture

```
Internet → Nginx (SSL) →
    ├── /api  → FastAPI (Uvicorn, port 8000)
    └── /     → Next.js (port 3000)

Services:
- PostgreSQL 15 (port 5432)
- Redis 7 (port 6379) — Celery broker + cache
- FastAPI backend
- Next.js frontend
- Celery worker
- Celery Beat (scheduler)

All containerized with Docker Compose
SSL via Let's Encrypt / Certbot
Domain: jarvis.alltame.kz
```

---

## 8. Monitoring Strategy

- Structured JSON logging (structlog)
- Scan run metrics stored in DB
- Health check endpoint for uptime monitoring
- Telegram alert if scan fails 3 consecutive times
- Error tracking via Sentry (optional)

---

## 9. SaaS Scalability Plan

- Multi-tenancy via company_id on all records
- Per-company filter configurations (categories, min_budget, min_margin)
- JWT authentication with company scoping
- Subscription tiers: Basic (1 platform), Pro (both + AI), Enterprise (custom)
- Horizontal scaling: multiple Celery workers

---

## 10. Security

- All secrets via environment variables (.env)
- JWT tokens for API authentication
- bcrypt password hashing
- API rate limiting (slowapi)
- SQL injection prevention via SQLAlchemy ORM
- CORS configured for dashboard domain only
