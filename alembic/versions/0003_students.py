"""multi-student support

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "students",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("line_user_id", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("line_user_id", name="uq_students_line_user_id"),
    )
    op.create_index("ix_students_line_user_id", "students", ["line_user_id"])

    op.create_table(
        "task_completions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            sa.Integer(),
            sa.ForeignKey("students.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", "student_id", name="uq_task_student"),
    )
    op.create_index("ix_task_completions_task_id", "task_completions", ["task_id"])
    op.create_index("ix_task_completions_student_id", "task_completions", ["student_id"])

    op.create_table(
        "assignment_student_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "assignment_id",
            sa.Integer(),
            sa.ForeignKey("assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            sa.Integer(),
            sa.ForeignKey("students.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pushed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("assignment_id", "student_id", name="uq_assignment_student"),
    )
    op.create_index(
        "ix_assignment_student_state_assignment_id",
        "assignment_student_state",
        ["assignment_id"],
    )
    op.create_index(
        "ix_assignment_student_state_student_id",
        "assignment_student_state",
        ["student_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_assignment_student_state_student_id", table_name="assignment_student_state")
    op.drop_index("ix_assignment_student_state_assignment_id", table_name="assignment_student_state")
    op.drop_table("assignment_student_state")
    op.drop_index("ix_task_completions_student_id", table_name="task_completions")
    op.drop_index("ix_task_completions_task_id", table_name="task_completions")
    op.drop_table("task_completions")
    op.drop_index("ix_students_line_user_id", table_name="students")
    op.drop_table("students")
