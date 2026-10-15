"""merge uploads and terms acceptance

Revision ID: 19c528bf1626
Revises: d3f7a91c4e58, 32120c241602
Create Date: 2026-10-15 14:20:45.422690

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "19c528bf1626"
down_revision: str | Sequence[str] | None = ("d3f7a91c4e58", "32120c241602")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
