"""normalize Vietnamese phone numbers

Revision ID: a61f82bc0b37
Revises: 9d2a7b5c1e44
Create Date: 2026-10-18 14:20:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a61f82bc0b37"
down_revision: str | None = "9d2a7b5c1e44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Older normalize_phone versions stored +8409... as 009.... Only update a
    # user when the canonical value is not already owned by another account.
    op.execute(
        """
        UPDATE users AS legacy
        SET phone = substr(legacy.phone, 2)
        WHERE legacy.phone LIKE '00%'
          AND length(legacy.phone) = 11
          AND NOT EXISTS (
              SELECT 1
              FROM users AS canonical
              WHERE canonical.phone = substr(legacy.phone, 2)
          )
        """
    )
    op.execute(
        """
        UPDATE orders
        SET recipient_phone = substr(recipient_phone, 2)
        WHERE recipient_phone LIKE '00%'
          AND length(recipient_phone) = 11
        """
    )


def downgrade() -> None:
    # Data normalization is intentionally irreversible.
    pass
