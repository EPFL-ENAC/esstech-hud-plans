"""add user terms acceptance columns

Revision ID: d3f7a91c4e58
Revises: c82a6f419d03
Create Date: 2026-09-09 00:06:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3f7a91c4e58"
down_revision: str | Sequence[str] | None = "c82a6f419d03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("terms_accepted_version", sa.String(), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "terms_accepted_at")
    op.drop_column("users", "terms_accepted_version")
