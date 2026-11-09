"""add funnel_step, fbclid, lead drop-off tracking, and discipline tracker to users

Revision ID: 0010_lead_funnel_and_discipline
Revises: 0009_unify_strategy_version
"""

from alembic import op
import sqlalchemy as sa

revision = '0010_lead_funnel_and_discipline'
down_revision = '0009_unify_strategy_version'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column('funnel_step', sa.String(length=32), nullable=False, server_default='1_STARTED'))
        batch_op.add_column(sa.Column('step_updated_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('fbclid', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('consecutive_wins', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('session_cooldown_until', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('last_reminded_step', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('last_reminded_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index('ix_users_funnel_step', ['funnel_step'])


def downgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_index('ix_users_funnel_step')
        batch_op.drop_column('last_reminded_at')
        batch_op.drop_column('last_reminded_step')
        batch_op.drop_column('session_cooldown_until')
        batch_op.drop_column('consecutive_wins')
        batch_op.drop_column('fbclid')
        batch_op.drop_column('step_updated_at')
        batch_op.drop_column('funnel_step')
