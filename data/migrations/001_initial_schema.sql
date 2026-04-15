-- JARVIS Tender AI — Initial Database Schema
-- Version: 1.0.0
-- Run: psql -U jarvis -d jarvis_db -f 001_initial_schema.sql

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Companies (SaaS multi-tenancy) ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    subscription_plan VARCHAR(50) DEFAULT 'basic',
    is_active BOOLEAN DEFAULT TRUE,
    settings JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Users ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES companies(id),
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255),
    telegram_chat_id BIGINT,
    role VARCHAR(50) DEFAULT 'user',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Tenders (parent announcements) ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tenders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform VARCHAR(50) NOT NULL,
    external_id VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'published',
    title TEXT NOT NULL,
    description TEXT,
    procurement_method VARCHAR(100),
    budget NUMERIC(18, 2),
    currency VARCHAR(10) DEFAULT 'KZT',
    customer_name TEXT,
    customer_bin VARCHAR(20),
    customer_region VARCHAR(100),
    published_at TIMESTAMPTZ,
    deadline_at TIMESTAMPTZ,
    category VARCHAR(100),
    raw_data JSONB DEFAULT '{}',
    documents JSONB DEFAULT '[]',
    first_seen_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_tender_platform_external UNIQUE (platform, external_id)
);

CREATE INDEX IF NOT EXISTS idx_tenders_platform ON tenders(platform);
CREATE INDEX IF NOT EXISTS idx_tenders_status ON tenders(status);
CREATE INDEX IF NOT EXISTS idx_tenders_deadline ON tenders(deadline_at);
CREATE INDEX IF NOT EXISTS idx_tenders_category ON tenders(category);
CREATE INDEX IF NOT EXISTS idx_tenders_first_seen ON tenders(first_seen_at DESC);

-- ── Tender Lots (individual procurement units — what suppliers bid on) ────────
CREATE TABLE IF NOT EXISTS tender_lots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tender_id UUID NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
    platform VARCHAR(50) NOT NULL,
    lot_external_id VARCHAR(255) NOT NULL,
    lot_number INTEGER,
    title TEXT NOT NULL,
    description TEXT,
    technical_spec_text TEXT,
    quantity NUMERIC(18, 4),
    unit VARCHAR(100),
    budget NUMERIC(18, 2),
    currency VARCHAR(10) DEFAULT 'KZT',
    category VARCHAR(50),
    status VARCHAR(50) DEFAULT 'published',
    deadline_at TIMESTAMPTZ,
    documents JSONB DEFAULT '[]',
    raw_data JSONB DEFAULT '{}',
    is_analyzed BOOLEAN DEFAULT FALSE,
    is_profitable BOOLEAN,
    confidence_level VARCHAR(20),
    profit_margin_percent NUMERIC(5, 2),
    notification_sent BOOLEAN DEFAULT FALSE,
    first_seen_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_lot_platform_external UNIQUE (platform, lot_external_id)
);

CREATE INDEX IF NOT EXISTS idx_lots_tender_id ON tender_lots(tender_id);
CREATE INDEX IF NOT EXISTS idx_lots_platform ON tender_lots(platform);
CREATE INDEX IF NOT EXISTS idx_lots_category ON tender_lots(category);
CREATE INDEX IF NOT EXISTS idx_lots_is_profitable ON tender_lots(is_profitable);
CREATE INDEX IF NOT EXISTS idx_lots_confidence ON tender_lots(confidence_level);
CREATE INDEX IF NOT EXISTS idx_lots_first_seen ON tender_lots(first_seen_at DESC);

-- Full-text search index on lot title
CREATE INDEX IF NOT EXISTS idx_lots_title_fts
    ON tender_lots USING gin(to_tsvector('russian', title));

-- ── Tender Lot Analyses (AI extraction results) ───────────────────────────────
CREATE TABLE IF NOT EXISTS tender_lot_analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lot_id UUID NOT NULL REFERENCES tender_lots(id) ON DELETE CASCADE,
    product_name TEXT,
    product_name_en TEXT,
    brand_model TEXT,
    dimensions TEXT,
    technical_params JSONB DEFAULT '{}',
    materials TEXT,
    quantity_extracted NUMERIC,
    unit_extracted VARCHAR(100),
    analogs_allowed BOOLEAN,
    spec_clarity VARCHAR(20),
    key_requirements JSONB DEFAULT '[]',
    ai_summary_ru TEXT,
    is_software_related BOOLEAN DEFAULT FALSE,
    software_type VARCHAR(100),
    raw_ai_response JSONB DEFAULT '{}',
    ai_model VARCHAR(100),
    extraction_confidence NUMERIC(3, 2),
    analyzed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lot_analyses_lot_id ON tender_lot_analyses(lot_id);

-- ── Tender Analyses (parent-level, kept for backward compat) ─────────────────
CREATE TABLE IF NOT EXISTS tender_analyses (
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
    spec_clarity VARCHAR(20),
    extracted_specs JSONB DEFAULT '{}',
    ai_summary TEXT,
    ai_model VARCHAR(100),
    analyzed_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Suppliers ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS suppliers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    country VARCHAR(50),
    source VARCHAR(100),
    contact_info JSONB DEFAULT '{}',
    rating NUMERIC(3, 2),
    verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Supplier Matches ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS supplier_matches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lot_id UUID REFERENCES tender_lots(id) ON DELETE CASCADE,
    tender_id UUID REFERENCES tenders(id) ON DELETE CASCADE,
    supplier_id UUID REFERENCES suppliers(id),
    product_name TEXT,
    unit_price NUMERIC(18, 2),
    currency VARCHAR(10) DEFAULT 'USD',
    unit_price_kzt NUMERIC(18, 2),
    moq INTEGER,
    lead_time_days INTEGER,
    match_score NUMERIC(3, 2),
    source_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_supplier_matches_lot ON supplier_matches(lot_id);

-- ── Logistics Estimates ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS logistics_estimates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tender_id UUID REFERENCES tenders(id) ON DELETE CASCADE,
    lot_id UUID REFERENCES tender_lots(id) ON DELETE CASCADE,
    origin_country VARCHAR(50),
    shipping_cost NUMERIC(18, 2),
    customs_duty NUMERIC(18, 2),
    vat_amount NUMERIC(18, 2),
    total_logistics NUMERIC(18, 2),
    lead_time_days INTEGER,
    route TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Profitability Analyses ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS profitability_analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lot_id UUID REFERENCES tender_lots(id) ON DELETE CASCADE,
    tender_id UUID REFERENCES tenders(id) ON DELETE CASCADE,
    product_cost NUMERIC(18, 2),
    logistics_cost NUMERIC(18, 2),
    customs_cost NUMERIC(18, 2),
    vat_amount NUMERIC(18, 2),
    operational_costs NUMERIC(18, 2),
    total_cost NUMERIC(18, 2),
    expected_profit NUMERIC(18, 2),
    profit_margin_percent NUMERIC(5, 2),
    is_profitable BOOLEAN DEFAULT FALSE,
    confidence_level VARCHAR(20),
    confidence_score NUMERIC(3, 2),
    recommended_bid NUMERIC(18, 2),
    safe_bid NUMERIC(18, 2),
    aggressive_bid NUMERIC(18, 2),
    risk_level VARCHAR(20),
    origin_country VARCHAR(10),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_profitability_lot ON profitability_analyses(lot_id);
CREATE INDEX IF NOT EXISTS idx_profitability_profitable ON profitability_analyses(is_profitable);

-- ── Notifications ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tender_id UUID REFERENCES tenders(id),
    lot_id UUID REFERENCES tender_lots(id),
    channel VARCHAR(50) DEFAULT 'telegram',
    recipient VARCHAR(255),
    message TEXT,
    sent_at TIMESTAMPTZ DEFAULT NOW(),
    status VARCHAR(50) DEFAULT 'sent'
);

-- ── User Actions ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tender_id UUID REFERENCES tenders(id),
    lot_id UUID REFERENCES tender_lots(id),
    user_id UUID REFERENCES users(id),
    action VARCHAR(50) NOT NULL,
    actual_bid_amount NUMERIC(18, 2),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_actions_lot ON user_actions(lot_id);

-- ── Scan Runs ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS scan_runs (
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

CREATE INDEX IF NOT EXISTS idx_scan_runs_started ON scan_runs(started_at DESC);

-- ── Scan State (incremental scanning position) ────────────────────────────────
CREATE TABLE IF NOT EXISTS scan_states (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform VARCHAR(50) UNIQUE NOT NULL,
    last_tender_id VARCHAR(255),
    last_tender_int_id BIGINT,
    last_scanned_page BIGINT DEFAULT 0,
    last_scan_started_at TIMESTAMPTZ,
    last_scan_completed_at TIMESTAMPTZ,
    last_successful_scan_at TIMESTAMPTZ,
    total_tenders_processed BIGINT DEFAULT 0,
    total_lots_processed BIGINT DEFAULT 0,
    total_profitable_found BIGINT DEFAULT 0,
    is_scanning BOOLEAN DEFAULT FALSE,
    error_count BIGINT DEFAULT 0,
    last_error VARCHAR(500),
    extra JSONB DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Seed initial scan states ──────────────────────────────────────────────────
INSERT INTO scan_states (platform) VALUES ('goszakup') ON CONFLICT (platform) DO NOTHING;
INSERT INTO scan_states (platform) VALUES ('zakupsk') ON CONFLICT (platform) DO NOTHING;

-- ── Seed default company and user (single-user mode) ─────────────────────────
INSERT INTO companies (id, name, subscription_plan)
VALUES ('00000000-0000-0000-0000-000000000001', 'Default Company', 'pro')
ON CONFLICT DO NOTHING;

INSERT INTO users (id, company_id, email, role)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000001',
    'admin@jarvis.local',
    'admin'
) ON CONFLICT DO NOTHING;
