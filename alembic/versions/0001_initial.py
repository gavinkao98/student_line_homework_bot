"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-21

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assignments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("assigned_date", sa.Date(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("pushed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_assignments_assigned_date", "assignments", ["assigned_date"], unique=True)

    op.create_table(
        "photos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("assignments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("line_message_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("file_path", sa.String(length=512), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_photos_assignment_id", "photos", ["assignment_id"])

    op.create_table(
        "event_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_event_log_event_type", "event_log", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_event_log_event_type", table_name="event_log")
    op.drop_table("event_log")
    op.drop_index("ix_photos_assignment_id", table_name="photos")
    op.drop_table("photos")
    op.drop_index("ix_assignments_assigned_date", table_name="assignments")
    op.drop_table("assignments")
