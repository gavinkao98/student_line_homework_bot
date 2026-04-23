"""inline stuck flow + completion gate

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("students") as b:
        b.add_column(sa.Column("awaiting_stuck_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("assignment_student_state") as b:
        b.add_column(sa.Column("stuck_submitted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("assignment_student_state") as b:
        b.drop_column("stuck_submitted_at")
    with op.batch_alter_table("students") as b:
        b.drop_column("awaiting_stuck_at")
