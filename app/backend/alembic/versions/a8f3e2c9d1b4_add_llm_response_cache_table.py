"""add_llm_response_cache_table

Revision ID: a8f3e2c9d1b4
Revises: c5874ba3b447
Create Date: 2025-10-01 10:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8f3e2c9d1b4'
down_revision: Union[str, None] = 'c5874ba3b447'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create llm_response_cache table
    op.create_table(
        "llm_response_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("analyst_name", sa.String(length=100), nullable=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),  # SHA256 hash
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("response_json", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.Column("model_provider", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    # Create indexes for efficient lookups
    op.create_index(op.f("ix_llm_response_cache_id"), "llm_response_cache", ["id"], unique=False)
    op.create_index(op.f("ix_llm_response_cache_ticker"), "llm_response_cache", ["ticker"], unique=False)
    op.create_index(op.f("ix_llm_response_cache_analyst_name"), "llm_response_cache", ["analyst_name"], unique=False)
    # Composite index for fast cache lookups
    op.create_index(
        "ix_llm_response_cache_lookup",
        "llm_response_cache",
        ["ticker", "analyst_name", "prompt_hash"],
        unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_llm_response_cache_lookup", table_name="llm_response_cache")
    op.drop_index(op.f("ix_llm_response_cache_analyst_name"), table_name="llm_response_cache")
    op.drop_index(op.f("ix_llm_response_cache_ticker"), table_name="llm_response_cache")
    op.drop_index(op.f("ix_llm_response_cache_id"), table_name="llm_response_cache")
    op.drop_table("llm_response_cache")
