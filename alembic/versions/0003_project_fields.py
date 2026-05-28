"""add mini-project fields to thoughts

Revision ID: 0003_project_fields
Revises: 0002_thought_route
Create Date: 2026-05-29

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_project_fields"
down_revision: Union[str, None] = "0002_thought_route"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("thoughts", sa.Column("project_title", sa.Text(), nullable=True))
    op.add_column("thoughts", sa.Column("project_goal", sa.Text(), nullable=True))
    op.add_column(
        "thoughts",
        sa.Column("project_steps", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "thoughts",
        sa.Column("success_criteria", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("thoughts", "success_criteria")
    op.drop_column("thoughts", "project_steps")
    op.drop_column("thoughts", "project_goal")
    op.drop_column("thoughts", "project_title")
