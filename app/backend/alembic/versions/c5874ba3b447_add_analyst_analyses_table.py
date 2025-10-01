"""add_analyst_analyses_table

Revision ID: c5874ba3b447
Revises: d5e78f9a1b2c
Create Date: 2025-10-01 06:51:17.244292

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5874ba3b447'
down_revision: Union[str, None] = 'd5e78f9a1b2c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create analyst_analyses table
    op.create_table(
        "analyst_analyses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.Column("session_id", sa.String(length=100), nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("analyst_name", sa.String(length=100), nullable=False),
        sa.Column("signal", sa.String(length=20), nullable=False),
        sa.Column("signal_numeric", sa.String(length=20), nullable=True),
        sa.Column("confidence", sa.String(length=20), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.Column("model_provider", sa.String(length=50), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_analyst_analyses_id"), "analyst_analyses", ["id"], unique=False)
    op.create_index(op.f("ix_analyst_analyses_session_id"), "analyst_analyses", ["session_id"], unique=False)
    op.create_index(op.f("ix_analyst_analyses_ticker"), "analyst_analyses", ["ticker"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_analyst_analyses_ticker"), table_name="analyst_analyses")
    op.drop_index(op.f("ix_analyst_analyses_session_id"), table_name="analyst_analyses")
    op.drop_index(op.f("ix_analyst_analyses_id"), table_name="analyst_analyses")
    op.drop_table("analyst_analyses")
