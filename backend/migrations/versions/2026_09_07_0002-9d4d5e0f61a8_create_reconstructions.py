"""create reconstructions

Revision ID: 9d4d5e0f61a8
Revises: 62f75ed81cd4
Create Date: 2026-09-07 00:02:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d4d5e0f61a8"
down_revision: str | Sequence[str] | None = "62f75ed81cd4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reconstructions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("building_id", sa.Uuid(), nullable=False),
        sa.Column("prefect_workflow_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("workspace_directory", sa.String(), nullable=True),
        sa.Column("input_video_path", sa.String(), nullable=True),
        sa.Column("raw_frames_directory", sa.String(), nullable=True),
        sa.Column("frames_directory", sa.String(), nullable=True),
        sa.Column("colmap_directory", sa.String(), nullable=True),
        sa.Column("splat_path", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "progress BETWEEN 0 AND 1",
            name="ck_reconstructions_progress_range",
        ),
        sa.CheckConstraint(
            "status IN ("
            "'preparing', 'scheduled', 'running', 'completed', "
            "'failed', 'cancelled', 'crashed'"
            ")",
            name="ck_reconstructions_status",
        ),
        sa.ForeignKeyConstraint(
            ["building_id"],
            ["buildings.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_reconstructions_building_id",
        "reconstructions",
        ["building_id"],
        unique=False,
    )
    op.create_index(
        "ix_reconstructions_prefect_workflow_id",
        "reconstructions",
        ["prefect_workflow_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reconstructions_prefect_workflow_id",
        table_name="reconstructions",
    )
    op.drop_index("ix_reconstructions_building_id", table_name="reconstructions")
    op.drop_table("reconstructions")
