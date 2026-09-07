"""create buildings

Revision ID: 62f75ed81cd4
Revises: 1f9c3a8d7b42
Create Date: 2026-09-06 00:01:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "62f75ed81cd4"
down_revision: str | Sequence[str] | None = "1f9c3a8d7b42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "buildings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "latitude BETWEEN -90 AND 90",
            name="ck_buildings_latitude_range",
        ),
        sa.CheckConstraint(
            "longitude BETWEEN -180 AND 180",
            name="ck_buildings_longitude_range",
        ),
        sa.CheckConstraint(
            "length(trim(name)) > 0",
            name="ck_buildings_name_nonempty",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_buildings_user_id",
        "buildings",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_buildings_user_id", table_name="buildings")
    op.drop_table("buildings")
