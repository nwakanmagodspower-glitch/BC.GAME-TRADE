"""telegram update receipts

Revision ID: 0003_telegram_update_receipts
Revises: 0002_onboarding_state
Create Date: 2026-08-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0003_telegram_update_receipts'
down_revision: Union[str, None] = '0002_onboarding_state'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'telegram_update_receipts',
        sa.Column('update_id', sa.BigInteger(), primary_key=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('telegram_update_receipts')
