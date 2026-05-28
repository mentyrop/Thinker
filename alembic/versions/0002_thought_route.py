"""add recommended_route and confidence to thoughts

Revision ID: 0002_thought_route
Revises: 0001_initial
Create Date: 2026-05-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_thought_route"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "thoughts",
        sa.Column("recommended_route", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "thoughts",
        sa.Column("confidence", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("thoughts", "confidence")
    op.drop_column("thoughts", "recommended_route")
