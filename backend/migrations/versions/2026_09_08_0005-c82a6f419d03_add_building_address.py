"""add optional building address

Revision ID: c82a6f419d03
Revises: b51e8c2d7a90
Create Date: 2026-09-08 00:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c82a6f419d03"
down_revision: str | Sequence[str] | None = "b51e8c2d7a90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("buildings", sa.Column("address", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("buildings", "address")
