"""add detrade_ws_token column to runtime_settings for persistent hot-reload

Revision ID: 0008_detrade_token_store
Revises: 0007_security_delivery_hardening
"""

from alembic import op
import sqlalchemy as sa

revision = '0008_detrade_token_store'
down_revision = '0007_security_delivery_hardening'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # runtime_settings already exists (created in 0001_initial).
    # We only need to widen the value column so a full JWT (≤ 2 KB) can be stored.
    # The column is VARCHAR(255) in the original schema; alter it to TEXT so any
    # JWT length is accepted without a schema change per environment.
    op.alter_column(
        'runtime_settings',
        'value',
        existing_type=sa.String(255),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        'runtime_settings',
        'value',
        existing_type=sa.Text(),
        type_=sa.String(255),
        existing_nullable=False,
    )
