"""Initial schema — all tables

Revision ID: 0001
Revises:
Create Date: 2026-03-11
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Run the raw SQL migration for speed and reliability
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ── companies ────────────────────────────────────────────────────────────
    op.create_table(
        "companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("subscription_plan", sa.String(50), server_default="basic"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("settings", postgresql.JSONB(), server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── users ────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("hashed_password", sa.String(255)),
        sa.Column("telegram_chat_id", sa.BigInteger()),
        sa.Column("role", sa.String(50), server_default="user"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── tenders ──────────────────────────────────────────────────────────────
    op.create_table(
        "tenders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="published"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("procurement_method", sa.String(100)),
        sa.Column("budget", sa.Numeric(18, 2)),
        sa.Column("currency", sa.String(10), server_default="KZT"),
        sa.Column("customer_name", sa.Text()),
        sa.Column("customer_bin", sa.String(20)),
        sa.Column("customer_region", sa.String(100)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("deadline_at", sa.DateTime(timezone=True)),
        sa.Column("category", sa.String(100)),
        sa.Column("raw_data", postgresql.JSONB(), server_default="{}"),
        sa.Column("documents", postgresql.JSONB(), server_default="[]"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("platform", "external_id", name="uq_tender_platform_external"),
    )
    op.create_index("idx_tenders_platform", "tenders", ["platform"])
    op.create_index("idx_tenders_deadline", "tenders", ["deadline_at"])
    op.create_index("idx_tenders_category", "tenders", ["category"])
    op.create_index("idx_tenders_first_seen", "tenders", ["first_seen_at"], postgresql_ops={"first_seen_at": "DESC"})

    # ── tender_lots ───────────────────────────────────────────────────────────
    op.create_table(
        "tender_lots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tender_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("lot_external_id", sa.String(255), nullable=False),
        sa.Column("lot_number", sa.Integer()),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("technical_spec_text", sa.Text()),
        sa.Column("quantity", sa.Numeric(18, 4)),
        sa.Column("unit", sa.String(100)),
        sa.Column("budget", sa.Numeric(18, 2)),
        sa.Column("currency", sa.String(10), server_default="KZT"),
        sa.Column("category", sa.String(50)),
        sa.Column("status", sa.String(50), server_default="published"),
        sa.Column("deadline_at", sa.DateTime(timezone=True)),
        sa.Column("documents", postgresql.JSONB(), server_default="[]"),
        sa.Column("raw_data", postgresql.JSONB(), server_default="{}"),
        sa.Column("is_analyzed", sa.Boolean(), server_default="false"),
        sa.Column("is_profitable", sa.Boolean()),
        sa.Column("confidence_level", sa.String(20)),
        sa.Column("profit_margin_percent", sa.Numeric(5, 2)),
        sa.Column("notification_sent", sa.Boolean(), server_default="false"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("platform", "lot_external_id", name="uq_lot_platform_external"),
    )
    op.create_index("idx_lots_tender_id", "tender_lots", ["tender_id"])
    op.create_index("idx_lots_platform", "tender_lots", ["platform"])
    op.create_index("idx_lots_category", "tender_lots", ["category"])
    op.create_index("idx_lots_is_profitable", "tender_lots", ["is_profitable"])
    op.create_index("idx_lots_first_seen", "tender_lots", ["first_seen_at"], postgresql_ops={"first_seen_at": "DESC"})

    # ── tender_lot_analyses ───────────────────────────────────────────────────
    op.create_table(
        "tender_lot_analyses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tender_lots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_name", sa.Text()),
        sa.Column("product_name_en", sa.Text()),
        sa.Column("brand_model", sa.Text()),
        sa.Column("dimensions", sa.Text()),
        sa.Column("technical_params", postgresql.JSONB(), server_default="{}"),
        sa.Column("materials", sa.Text()),
        sa.Column("quantity_extracted", sa.Numeric()),
        sa.Column("unit_extracted", sa.String(100)),
        sa.Column("analogs_allowed", sa.Boolean()),
        sa.Column("spec_clarity", sa.String(20)),
        sa.Column("key_requirements", postgresql.JSONB(), server_default="[]"),
        sa.Column("ai_summary_ru", sa.Text()),
        sa.Column("is_software_related", sa.Boolean(), server_default="false"),
        sa.Column("software_type", sa.String(100)),
        sa.Column("raw_ai_response", postgresql.JSONB(), server_default="{}"),
        sa.Column("ai_model", sa.String(100)),
        sa.Column("extraction_confidence", sa.Numeric(3, 2)),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── suppliers ────────────────────────────────────────────────────────────
    op.create_table(
        "suppliers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("country", sa.String(50)),
        sa.Column("source", sa.String(100)),
        sa.Column("contact_info", postgresql.JSONB(), server_default="{}"),
        sa.Column("rating", sa.Numeric(3, 2)),
        sa.Column("verified", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── supplier_matches ──────────────────────────────────────────────────────
    op.create_table(
        "supplier_matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tender_lots.id", ondelete="CASCADE"), nullable=True),
        sa.Column("tender_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenders.id", ondelete="CASCADE"), nullable=True),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("suppliers.id")),
        sa.Column("product_name", sa.Text()),
        sa.Column("unit_price", sa.Numeric(18, 2)),
        sa.Column("currency", sa.String(10), server_default="USD"),
        sa.Column("unit_price_kzt", sa.Numeric(18, 2)),
        sa.Column("moq", sa.Integer()),
        sa.Column("lead_time_days", sa.Integer()),
        sa.Column("match_score", sa.Numeric(3, 2)),
        sa.Column("source_url", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_supplier_matches_lot", "supplier_matches", ["lot_id"])

    # ── profitability_analyses ────────────────────────────────────────────────
    op.create_table(
        "profitability_analyses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tender_lots.id", ondelete="CASCADE"), nullable=True),
        sa.Column("tender_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenders.id", ondelete="CASCADE"), nullable=True),
        sa.Column("product_cost", sa.Numeric(18, 2)),
        sa.Column("logistics_cost", sa.Numeric(18, 2)),
        sa.Column("customs_cost", sa.Numeric(18, 2)),
        sa.Column("vat_amount", sa.Numeric(18, 2)),
        sa.Column("operational_costs", sa.Numeric(18, 2)),
        sa.Column("total_cost", sa.Numeric(18, 2)),
        sa.Column("expected_profit", sa.Numeric(18, 2)),
        sa.Column("profit_margin_percent", sa.Numeric(5, 2)),
        sa.Column("is_profitable", sa.Boolean(), server_default="false"),
        sa.Column("confidence_level", sa.String(20)),
        sa.Column("confidence_score", sa.Numeric(3, 2)),
        sa.Column("recommended_bid", sa.Numeric(18, 2)),
        sa.Column("safe_bid", sa.Numeric(18, 2)),
        sa.Column("aggressive_bid", sa.Numeric(18, 2)),
        sa.Column("risk_level", sa.String(20)),
        sa.Column("origin_country", sa.String(10)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_profitability_lot", "profitability_analyses", ["lot_id"])
    op.create_index("idx_profitability_profitable", "profitability_analyses", ["is_profitable"])

    # ── logistics_estimates ───────────────────────────────────────────────────
    op.create_table(
        "logistics_estimates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tender_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenders.id", ondelete="CASCADE"), nullable=True),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tender_lots.id", ondelete="CASCADE"), nullable=True),
        sa.Column("origin_country", sa.String(50)),
        sa.Column("shipping_cost", sa.Numeric(18, 2)),
        sa.Column("customs_duty", sa.Numeric(18, 2)),
        sa.Column("vat_amount", sa.Numeric(18, 2)),
        sa.Column("total_logistics", sa.Numeric(18, 2)),
        sa.Column("lead_time_days", sa.Integer()),
        sa.Column("route", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── notifications ─────────────────────────────────────────────────────────
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tender_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenders.id")),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tender_lots.id")),
        sa.Column("channel", sa.String(50), server_default="telegram"),
        sa.Column("recipient", sa.String(255)),
        sa.Column("message", sa.Text()),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("status", sa.String(50), server_default="sent"),
    )

    # ── user_actions ──────────────────────────────────────────────────────────
    op.create_table(
        "user_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tender_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenders.id")),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tender_lots.id")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("actual_bid_amount", sa.Numeric(18, 2)),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── scan_runs ─────────────────────────────────────────────────────────────
    op.create_table(
        "scan_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("platform", sa.String(50)),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("tenders_found", sa.Integer(), server_default="0"),
        sa.Column("tenders_new", sa.Integer(), server_default="0"),
        sa.Column("profitable_found", sa.Integer(), server_default="0"),
        sa.Column("status", sa.String(50), server_default="running"),
        sa.Column("error_message", sa.Text()),
    )
    op.create_index("idx_scan_runs_started", "scan_runs", ["started_at"], postgresql_ops={"started_at": "DESC"})

    # ── scan_states ───────────────────────────────────────────────────────────
    op.create_table(
        "scan_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("platform", sa.String(50), unique=True, nullable=False),
        sa.Column("last_tender_id", sa.String(255)),
        sa.Column("last_tender_int_id", sa.BigInteger()),
        sa.Column("last_scanned_page", sa.BigInteger(), server_default="0"),
        sa.Column("last_scan_started_at", sa.DateTime(timezone=True)),
        sa.Column("last_scan_completed_at", sa.DateTime(timezone=True)),
        sa.Column("last_successful_scan_at", sa.DateTime(timezone=True)),
        sa.Column("total_tenders_processed", sa.BigInteger(), server_default="0"),
        sa.Column("total_lots_processed", sa.BigInteger(), server_default="0"),
        sa.Column("total_profitable_found", sa.BigInteger(), server_default="0"),
        sa.Column("is_scanning", sa.Boolean(), server_default="false"),
        sa.Column("error_count", sa.BigInteger(), server_default="0"),
        sa.Column("last_error", sa.String(500)),
        sa.Column("extra", postgresql.JSONB(), server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── tender_analyses (legacy) ──────────────────────────────────────────────
    op.create_table(
        "tender_analyses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tender_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenders.id", ondelete="CASCADE")),
        sa.Column("product_name", sa.Text()),
        sa.Column("brand_model", sa.Text()),
        sa.Column("dimensions", sa.Text()),
        sa.Column("technical_params", postgresql.JSONB(), server_default="{}"),
        sa.Column("materials", sa.Text()),
        sa.Column("quantity", sa.Numeric()),
        sa.Column("unit", sa.String(50)),
        sa.Column("analogs_allowed", sa.Boolean()),
        sa.Column("spec_clarity", sa.String(20)),
        sa.Column("extracted_specs", postgresql.JSONB(), server_default="{}"),
        sa.Column("ai_summary", sa.Text()),
        sa.Column("ai_model", sa.String(100)),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── Seed data ─────────────────────────────────────────────────────────────
    op.execute("""
        INSERT INTO scan_states (platform) VALUES ('goszakup')
        ON CONFLICT (platform) DO NOTHING
    """)
    op.execute("""
        INSERT INTO scan_states (platform) VALUES ('zakupsk')
        ON CONFLICT (platform) DO NOTHING
    """)
    op.execute("""
        INSERT INTO companies (id, name, subscription_plan)
        VALUES ('00000000-0000-0000-0000-000000000001', 'Default Company', 'pro')
        ON CONFLICT DO NOTHING
    """)
    op.execute("""
        INSERT INTO users (id, company_id, email, role)
        VALUES (
            '00000000-0000-0000-0000-000000000001',
            '00000000-0000-0000-0000-000000000001',
            'admin@jarvis.local', 'admin'
        ) ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    tables = [
        "tender_analyses", "scan_states", "scan_runs",
        "user_actions", "notifications", "logistics_estimates",
        "profitability_analyses", "supplier_matches", "suppliers",
        "tender_lot_analyses", "tender_lots", "tenders",
        "users", "companies",
    ]
    for t in tables:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
