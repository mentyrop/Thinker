"""add research plan and delegation fields to thoughts

Revision ID: 0006_research_delegation
Revises: 0005_research_method
Create Date: 2026-05-29

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_research_delegation"
down_revision: Union[str, None] = "0005_research_method"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "thoughts",
        sa.Column("research_goal", sa.Text(), nullable=True),
    )
    op.add_column(
        "thoughts",
        sa.Column("research_steps", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "thoughts",
        sa.Column("first_research_step", sa.Text(), nullable=True),
    )
    op.add_column(
        "thoughts",
        sa.Column("delegation_text", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("thoughts", "delegation_text")
    op.drop_column("thoughts", "first_research_step")
    op.drop_column("thoughts", "research_steps")
    op.drop_column("thoughts", "research_goal")
