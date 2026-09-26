"""unify strategy_version for all historical signal records

Revision ID: 0009_unify_strategy_version
Revises: 0008_detrade_token_store
"""

from alembic import op

revision = '0009_unify_strategy_version'
down_revision = '0008_detrade_token_store'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Migrate any historical or legacy paper signals recorded under older versions
    # to the canonical locked version so paper-validation reports don't see version drift.
    op.execute(
        "UPDATE signals SET strategy_version = 'BTC_ORIGINAL_INTELLIGENCE_TIMER_V1' "
        "WHERE strategy_version != 'BTC_ORIGINAL_INTELLIGENCE_TIMER_V1'"
    )


def downgrade() -> None:
    pass
