"""drop stuck_submitted_at (gate feature removed)

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("assignment_student_state") as b:
        b.drop_column("stuck_submitted_at")


def downgrade() -> None:
    with op.batch_alter_table("assignment_student_state") as b:
        b.add_column(sa.Column("stuck_submitted_at", sa.DateTime(timezone=True), nullable=True))
