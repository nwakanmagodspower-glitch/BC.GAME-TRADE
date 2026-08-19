"""add onboarding state

Revision ID: 0002_onboarding_state
Revises: 0001_initial
"""

from alembic import op
import sqlalchemy as sa

revision = '0002_onboarding_state'
down_revision = '0001_initial'
branch_labels = None
depends_on = None

onboarding_step = sa.Enum(
    'START',
    'REGISTRATION',
    'DEPOSIT',
    'BC_ID',
    'PROFILE_PROOF',
    'DEPOSIT_PROOF',
    'REVIEW',
    'APPROVED',
    'RESUBMIT',
    name='onboardingstep',
)


def upgrade() -> None:
    onboarding_step.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'users',
        sa.Column('onboarding_step', onboarding_step, nullable=False, server_default='START'),
    )
    op.create_index('ix_users_onboarding_step', 'users', ['onboarding_step'], unique=False)
    # SQLite cannot execute ``ALTER COLUMN ... DROP DEFAULT``. Keeping the
    # bootstrap default in local SQLite databases is harmless; PostgreSQL,
    # which is the production database, still has the default removed.
    if op.get_bind().dialect.name != 'sqlite':
        op.alter_column('users', 'onboarding_step', server_default=None)


def downgrade() -> None:
    op.drop_index('ix_users_onboarding_step', table_name='users')
    op.drop_column('users', 'onboarding_step')
    onboarding_step.drop(op.get_bind(), checkfirst=True)
