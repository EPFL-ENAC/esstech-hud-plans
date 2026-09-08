"""index latest reconstruction lookup

Revision ID: b51e8c2d7a90
Revises: a42f9d8e7c31
Create Date: 2026-09-08 00:04:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "b51e8c2d7a90"
down_revision: str | Sequence[str] | None = "a42f9d8e7c31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_reconstructions_building_created_id",
        "reconstructions",
        ["building_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reconstructions_building_created_id", table_name="reconstructions"
    )
