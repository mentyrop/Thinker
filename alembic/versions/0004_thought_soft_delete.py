"""add is_deleted (soft delete) to thoughts

Revision ID: 0004_thought_soft_delete
Revises: 0003_project_fields
Create Date: 2026-05-29

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_thought_soft_delete"
down_revision: Union[str, None] = "0003_project_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "thoughts",
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("thoughts", "is_deleted")
