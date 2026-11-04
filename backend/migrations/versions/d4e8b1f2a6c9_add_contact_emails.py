"""add contact emails for OTP notifications

Revision ID: d4e8b1f2a6c9
Revises: c3f2a91d74ab
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e8b1f2a6c9"
down_revision: str | None = "c3f2a91d74ab"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = (("users", "email"), ("orders", "recipient_email"))


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table_name, column_name in COLUMNS:
        # app.bootstrap may already have added the column to a local SQLite DB.
        existing = {column["name"] for column in inspector.get_columns(table_name)}
        if column_name not in existing:
            op.add_column(
                table_name, sa.Column(column_name, sa.String(length=254), nullable=True)
            )


def downgrade() -> None:
    for table_name, column_name in reversed(COLUMNS):
        op.drop_column(table_name, column_name)
