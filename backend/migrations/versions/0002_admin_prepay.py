"""Админка в боте, приглашения, выходные мастеров, блокировка клиентов, предоплата.

Revision ID: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tenants") as t:
        t.add_column(sa.Column("prepay_amount", sa.Integer, nullable=False, server_default="0"))
        t.add_column(sa.Column("payment_details", sa.Text))
        t.add_column(sa.Column("admin_invite_code", sa.String(32)))
    with op.batch_alter_table("masters") as t:
        t.add_column(sa.Column("invite_code", sa.String(32)))
    op.create_index("ix_masters_invite_code", "masters", ["invite_code"], unique=True)
    with op.batch_alter_table("clients") as t:
        t.add_column(sa.Column("is_blocked", sa.Boolean, nullable=False, server_default=sa.false()))
        t.add_column(sa.Column("created_at", sa.DateTime(timezone=True)))
    with op.batch_alter_table("bookings") as t:
        t.add_column(sa.Column("cancelled_by", sa.String(10)))
    op.create_table(
        "master_time_off",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("master_id", sa.Integer, sa.ForeignKey("masters.id"), nullable=False, index=True),
        sa.Column("day", sa.Date, nullable=False),
        sa.UniqueConstraint("master_id", "day"),
    )


def downgrade() -> None:
    op.drop_table("master_time_off")
    with op.batch_alter_table("bookings") as t:
        t.drop_column("cancelled_by")
    with op.batch_alter_table("clients") as t:
        t.drop_column("created_at")
        t.drop_column("is_blocked")
    op.drop_index("ix_masters_invite_code", "masters")
    with op.batch_alter_table("masters") as t:
        t.drop_column("invite_code")
    with op.batch_alter_table("tenants") as t:
        t.drop_column("admin_invite_code")
        t.drop_column("payment_details")
        t.drop_column("prepay_amount")
