"""initial tables: users, thoughts, calendar_events

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_telegram_id"), "users", ["telegram_id"], unique=True)

    op.create_table(
        "thoughts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("type", sa.String(length=50), nullable=True),
        sa.Column(
            "category",
            sa.String(length=50),
            server_default="journal",
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(length=50), server_default="new", nullable=False
        ),
        sa.Column("actionable", sa.Boolean(), nullable=True),
        sa.Column("can_delegate", sa.Boolean(), nullable=True),
        sa.Column("calendar_candidate", sa.Boolean(), nullable=True),
        sa.Column("needs_first_step", sa.Boolean(), nullable=True),
        sa.Column("needs_research", sa.Boolean(), nullable=True),
        sa.Column("suggested_first_step", sa.Text(), nullable=True),
        sa.Column("suggested_calendar_title", sa.Text(), nullable=True),
        sa.Column(
            "suggested_duration_minutes",
            sa.Integer(),
            server_default="30",
            nullable=False,
        ),
        sa.Column("llm_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_thoughts_user_id"), "thoughts", ["user_id"], unique=False)

    op.create_table(
        "calendar_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("thought_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("start_datetime", sa.DateTime(), nullable=False),
        sa.Column("end_datetime", sa.DateTime(), nullable=False),
        sa.Column("google_calendar_url", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["thought_id"], ["thoughts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_calendar_events_thought_id"),
        "calendar_events",
        ["thought_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_calendar_events_thought_id"), table_name="calendar_events")
    op.drop_table("calendar_events")
    op.drop_index(op.f("ix_thoughts_user_id"), table_name="thoughts")
    op.drop_table("thoughts")
    op.drop_index(op.f("ix_users_telegram_id"), table_name="users")
    op.drop_table("users")
