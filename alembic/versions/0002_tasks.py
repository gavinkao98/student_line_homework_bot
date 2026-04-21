"""add tasks table + backfill

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "assignment_id",
            sa.Integer(),
            sa.ForeignKey("assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tasks_assignment_id", "tasks", ["assignment_id"])

    # Backfill: one task per existing assignment, inheriting completed_at
    op.execute(
        """
        INSERT INTO tasks (assignment_id, position, text, completed_at)
        SELECT id, 0, content, completed_at FROM assignments
        """
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_assignment_id", table_name="tasks")
    op.drop_table("tasks")
