"""align compartments with the MQTT hardware specification

Revision ID: c3f2a91d74ab
Revises: a61f82bc0b37
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3f2a91d74ab"
down_revision: str | None = "a61f82bc0b37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "compartments",
        sa.Column("size", sa.String(length=8), nullable=False, server_default="S"),
    )
    op.execute("UPDATE compartments SET size = 'M' WHERE number = 2")
    op.execute("UPDATE compartments SET size = 'TECH' WHERE number = 4")
    op.alter_column("orders", "shipper_id", existing_type=sa.String(36), nullable=True)


def downgrade() -> None:
    op.alter_column("orders", "shipper_id", existing_type=sa.String(36), nullable=False)
    op.drop_column("compartments", "size")
