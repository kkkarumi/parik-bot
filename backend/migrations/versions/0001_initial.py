"""Исходная схема (как её создавал create_all в версии до 23.10.2026).

Revision ID: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ExcludeConstraint

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    pg = op.get_bind().dialect.name == "postgresql"
    if pg:
        op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("api_key", sa.String(64), nullable=False, unique=True),
        sa.Column("timezone", sa.String(40), nullable=False),
        sa.Column("admin_chat_id", sa.BigInteger),
        sa.Column("address", sa.String(200)),
        sa.Column("phone", sa.String(40)),
        sa.Column("work_hours_text", sa.String(120)),
        sa.Column("instagram_url", sa.String(200)),
        sa.Column("welcome_text", sa.Text),
    )
    op.create_table(
        "masters",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger),
        sa.Column("is_active", sa.Boolean, nullable=False),
    )
    op.create_table(
        "services",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("price", sa.Integer, nullable=False),
        sa.Column("duration_min", sa.Integer, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False),
    )
    op.create_table(
        "master_services",
        sa.Column("master_id", sa.Integer, sa.ForeignKey("masters.id"), primary_key=True),
        sa.Column("service_id", sa.Integer, sa.ForeignKey("services.id"), primary_key=True),
    )
    op.create_table(
        "working_hours",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("master_id", sa.Integer, sa.ForeignKey("masters.id"), nullable=False, index=True),
        sa.Column("weekday", sa.SmallInteger, nullable=False),
        sa.Column("start_time", sa.Time, nullable=False),
        sa.Column("end_time", sa.Time, nullable=False),
    )
    op.create_table(
        "clients",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("telegram_id", sa.BigInteger, nullable=False),
        sa.Column("username", sa.String(80)),
        sa.Column("name", sa.String(120)),
        sa.Column("phone", sa.String(32)),
        sa.Column("notes", sa.Text),
        sa.UniqueConstraint("tenant_id", "telegram_id"),
    )
    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("master_id", sa.Integer, sa.ForeignKey("masters.id"), nullable=False, index=True),
        sa.Column("service_id", sa.Integer, sa.ForeignKey("services.id"), nullable=False),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("clients.id"), nullable=False, index=True),
        sa.Column("starts_at", TS, nullable=False),
        sa.Column("ends_at", TS, nullable=False),
        sa.Column("price", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("client_confirmed", sa.Boolean, nullable=False),
        sa.Column("reminded_24h", sa.Boolean, nullable=False),
        sa.Column("reminded_2h", sa.Boolean, nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        *([ExcludeConstraint(("master_id", "="), (sa.text("tstzrange(starts_at, ends_at)"), "&&"),
                             name="bookings_no_overlap", where=sa.text("status <> 'cancelled'"),
                             using="gist")] if pg else []),
    )
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("booking_id", sa.Integer, sa.ForeignKey("bookings.id"), nullable=False, index=True),
        sa.Column("amount", sa.Integer, nullable=False),
        sa.Column("receipt_file_id", sa.String(200)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("booking_id", sa.Integer, sa.ForeignKey("bookings.id"), nullable=False, unique=True),
        sa.Column("rating", sa.SmallInteger, nullable=False),
        sa.Column("text", sa.Text),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    for t in ("reviews", "payments", "bookings", "clients", "working_hours", "master_services",
              "services", "masters", "tenants"):
        op.drop_table(t)
