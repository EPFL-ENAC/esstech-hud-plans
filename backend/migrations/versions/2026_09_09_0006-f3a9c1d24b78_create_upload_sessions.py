"""create upload sessions

Revision ID: f3a9c1d24b78
Revises: c82a6f419d03
Create Date: 2026-09-09 00:06:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3a9c1d24b78"
down_revision: str | Sequence[str] | None = "c82a6f419d03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "upload_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("building_id", sa.Uuid(), nullable=True),
        sa.Column("building_payload", sa.JSON(), nullable=True),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("file_extension", sa.String(), nullable=False),
        sa.Column("total_size", sa.BigInteger(), nullable=False),
        sa.Column("chunk_size", sa.BigInteger(), nullable=False),
        sa.Column("total_chunks", sa.BigInteger(), nullable=False),
        sa.Column("received_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("total_chunks >= 1", name="ck_upload_sessions_total_chunks"),
        sa.CheckConstraint(
            "received_bytes <= total_size",
            name="ck_upload_sessions_received_bytes",
        ),
        sa.CheckConstraint(
            "status IN ('uploading', 'finalized')",
            name="ck_upload_sessions_status",
        ),
        sa.ForeignKeyConstraint(
            ["building_id"],
            ["buildings.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_upload_sessions_user_id",
        "upload_sessions",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_upload_sessions_expires_at",
        "upload_sessions",
        ["expires_at"],
        unique=False,
    )
    op.create_table(
        "upload_chunks",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.BigInteger(), nullable=False),
        sa.Column("byte_offset", sa.BigInteger(), nullable=False),
        sa.Column("expected_size", sa.BigInteger(), nullable=False),
        sa.Column("expected_digest", sa.String(length=64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_digest", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["upload_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("session_id", "chunk_index"),
    )


def downgrade() -> None:
    op.drop_table("upload_chunks")
    op.drop_index("ix_upload_sessions_expires_at", table_name="upload_sessions")
    op.drop_index("ix_upload_sessions_user_id", table_name="upload_sessions")
    op.drop_table("upload_sessions")
