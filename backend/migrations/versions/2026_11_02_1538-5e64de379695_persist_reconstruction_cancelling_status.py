"""persist reconstruction cancelling status

Revision ID: 5e64de379695
Revises: 94e0cf75a7a5
Create Date: 2026-11-02 15:38:08.709985

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5e64de379695"
down_revision: str | Sequence[str] | None = "94e0cf75a7a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_reconstructions_status", "reconstructions", type_="check")
    op.create_check_constraint(
        "ck_reconstructions_status",
        "reconstructions",
        "status IN ('waiting_for_upload', 'preparing', 'scheduled', 'running', "
        "'cancelling', 'completed', 'failed', 'cancelled', 'crashed')",
    )


def downgrade() -> None:
    op.execute("LOCK TABLE reconstructions IN ACCESS EXCLUSIVE MODE")
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM reconstructions WHERE status = 'cancelling') THEN
                    RAISE EXCEPTION 'Cannot downgrade while reconstructions are cancelling; finish cancellation first';
                END IF;
            END;
            $$;
            """
        )
    )
    op.drop_constraint("ck_reconstructions_status", "reconstructions", type_="check")
    op.create_check_constraint(
        "ck_reconstructions_status",
        "reconstructions",
        "status IN ('waiting_for_upload', 'preparing', 'scheduled', 'running', "
        "'completed', 'failed', 'cancelled', 'crashed')",
    )
