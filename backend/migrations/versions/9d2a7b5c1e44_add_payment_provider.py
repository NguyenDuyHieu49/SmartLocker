"""add payment provider

Revision ID: 9d2a7b5c1e44
Revises: 88eb7465fada
Create Date: 2026-10-17 20:45:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d2a7b5c1e44"
down_revision: str | None = "88eb7465fada"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column(
            "provider",
            sa.String(length=24),
            nullable=False,
            server_default="mock",
        ),
    )
    op.add_column(
        "payment_webhook_events",
        sa.Column(
            "provider",
            sa.String(length=24),
            nullable=False,
            server_default="payos",
        ),
    )


def downgrade() -> None:
    op.drop_column("payment_webhook_events", "provider")
    op.drop_column("payments", "provider")
