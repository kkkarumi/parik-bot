"""Согласие на обработку ПДн (152-ФЗ) и отметка об удалении данных клиентом.

Оба поля nullable: у существующих клиентов согласие спросят при следующей записи, данные не меняются.

Revision ID: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("clients") as t:
        t.add_column(sa.Column("consent_at", sa.DateTime(timezone=True)))
        t.add_column(sa.Column("erased_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    with op.batch_alter_table("clients") as t:
        t.drop_column("erased_at")
        t.drop_column("consent_at")
