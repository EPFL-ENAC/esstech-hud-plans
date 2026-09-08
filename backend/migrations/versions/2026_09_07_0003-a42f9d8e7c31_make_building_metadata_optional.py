"""make building metadata optional

Revision ID: a42f9d8e7c31
Revises: 9d4d5e0f61a8
Create Date: 2026-09-07 00:03:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a42f9d8e7c31"
down_revision: str | Sequence[str] | None = "9d4d5e0f61a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("buildings") as batch_op:
        batch_op.drop_constraint("ck_buildings_name_nonempty", type_="check")
        batch_op.alter_column("latitude", existing_type=sa.Float(), nullable=True)
        batch_op.alter_column("longitude", existing_type=sa.Float(), nullable=True)
        batch_op.create_check_constraint(
            "ck_buildings_coordinates_complete",
            "(latitude IS NULL AND longitude IS NULL) OR "
            "(latitude IS NOT NULL AND longitude IS NOT NULL)",
        )


def downgrade() -> None:
    op.execute(
        sa.text("UPDATE buildings SET name = 'Unnamed building' WHERE trim(name) = ''")
    )
    op.execute(
        sa.text(
            "UPDATE buildings SET latitude = 0, longitude = 0 "
            "WHERE latitude IS NULL OR longitude IS NULL"
        )
    )
    with op.batch_alter_table("buildings") as batch_op:
        batch_op.drop_constraint(
            "ck_buildings_coordinates_complete",
            type_="check",
        )
        batch_op.alter_column("latitude", existing_type=sa.Float(), nullable=False)
        batch_op.alter_column("longitude", existing_type=sa.Float(), nullable=False)
        batch_op.create_check_constraint(
            "ck_buildings_name_nonempty",
            "length(trim(name)) > 0",
        )
