"""add research_method to thoughts

Revision ID: 0005_research_method
Revises: 0004_thought_soft_delete
Create Date: 2026-05-29

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_research_method"
down_revision: Union[str, None] = "0004_thought_soft_delete"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "thoughts",
        sa.Column("research_method", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("thoughts", "research_method")
