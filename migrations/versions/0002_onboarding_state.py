"""add onboarding state

Revision ID: 0002_onboarding_state
Revises: 0001_initial
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0002_onboarding_state'
down_revision = '0001_initial'
branch_labels = None
depends_on = None

ONBOARDING_VALUES = (
    'START',
    'REGISTRATION',
    'DEPOSIT',
    'BC_ID',
    'PROFILE_PROOF',
    'DEPOSIT_PROOF',
    'REVIEW',
    'APPROVED',
    'RESUBMIT',
)


def _onboarding_enum(bind):
    if bind.dialect.name == 'postgresql':
        postgresql.ENUM(*ONBOARDING_VALUES, name='onboardingstep').create(bind, checkfirst=True)
        return postgresql.ENUM(*ONBOARDING_VALUES, name='onboardingstep', create_type=False)
    return sa.Enum(*ONBOARDING_VALUES, name='onboardingstep')


def upgrade() -> None:
    bind = op.get_bind()
    onboarding_step = _onboarding_enum(bind)
    op.add_column(
        'users',
        sa.Column('onboarding_step', onboarding_step, nullable=False, server_default='START'),
    )
    op.create_index('ix_users_onboarding_step', 'users', ['onboarding_step'], unique=False)
    # SQLite cannot execute ``ALTER COLUMN ... DROP DEFAULT``. Keeping the
    # bootstrap default in local SQLite databases is harmless; PostgreSQL,
    # which is the production database, still has the default removed.
    if bind.dialect.name != 'sqlite':
        op.alter_column('users', 'onboarding_step', server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index('ix_users_onboarding_step', table_name='users')
    op.drop_column('users', 'onboarding_step')
    if bind.dialect.name == 'postgresql':
        postgresql.ENUM(*ONBOARDING_VALUES, name='onboardingstep').drop(bind, checkfirst=True)
    else:
        sa.Enum(*ONBOARDING_VALUES, name='onboardingstep').drop(bind, checkfirst=True)
