"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    user_status = sa.Enum('PENDING', 'APPROVED', 'REJECTED', 'SUSPENDED', name='userstatus')
    user_role = sa.Enum('USER', 'ADMIN', 'OWNER', name='userrole')
    verification_status = sa.Enum('COLLECTING', 'SUBMITTED', 'APPROVED', 'REJECTED', 'RESUBMIT', name='verificationstatus')
    signal_direction = sa.Enum('UP', 'DOWN', 'NO_TRADE', name='signaldirection')
    signal_status = sa.Enum('CANDIDATE', 'WAITING_ENTRY', 'ACTIVE', 'CANCELLED', 'EXPIRED', 'WIN', 'LOSS', 'TIE', 'NO_TRADE', name='signalstatus')

    bind = op.get_bind()
    for enum_type in (user_status, user_role, verification_status, signal_direction, signal_status):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('telegram_user_id', sa.BigInteger(), nullable=False),
        sa.Column('telegram_username', sa.String(length=255), nullable=True),
        sa.Column('first_name', sa.String(length=255), nullable=True),
        sa.Column('status', user_status, nullable=False),
        sa.Column('role', user_role, nullable=False),
        sa.Column('is_blocked', sa.Boolean(), nullable=False),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('telegram_user_id'),
    )
    op.create_index('ix_users_telegram_user_id', 'users', ['telegram_user_id'])
    op.create_index('ix_users_status', 'users', ['status'])

    op.create_table(
        'verification_requests',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('bcgame_user_id', sa.String(length=255), nullable=True),
        sa.Column('profile_proof_file_id', sa.Text(), nullable=True),
        sa.Column('deposit_proof_file_ids', sa.JSON(), nullable=True),
        sa.Column('status', verification_status, nullable=False),
        sa.Column('admin_note', sa.Text(), nullable=True),
        sa.Column('reviewed_by', sa.BigInteger(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_verification_requests_user_id', 'verification_requests', ['user_id'])
    op.create_index('ix_verification_requests_bcgame_user_id', 'verification_requests', ['bcgame_user_id'])
    op.create_index('ix_verification_requests_status', 'verification_requests', ['status'])

    op.create_table(
        'signals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('requested_by_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('market', sa.String(length=40), nullable=False),
        sa.Column('product', sa.String(length=60), nullable=False),
        sa.Column('direction', signal_direction, nullable=False),
        sa.Column('status', signal_status, nullable=False),
        sa.Column('strategy_version', sa.String(length=80), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('entry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('entry_window_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('entry_window_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expiry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reference_entry_price', sa.Float(), nullable=True),
        sa.Column('reference_expiry_price', sa.Float(), nullable=True),
        sa.Column('features_snapshot', sa.JSON(), nullable=True),
        sa.Column('decision_reason', sa.Text(), nullable=True),
    )
    op.create_index('ix_signals_requested_by_user_id', 'signals', ['requested_by_user_id'])
    op.create_index('ix_signals_market', 'signals', ['market'])
    op.create_index('ix_signals_direction', 'signals', ['direction'])
    op.create_index('ix_signals_status', 'signals', ['status'])
    op.create_index('ix_signals_strategy_version', 'signals', ['strategy_version'])

    op.create_table(
        'broadcasts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('created_by', sa.BigInteger(), nullable=False),
        sa.Column('recipient_count', sa.Integer(), nullable=False),
        sa.Column('sent_count', sa.Integer(), nullable=False),
        sa.Column('failed_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('broadcasts')
    op.drop_index('ix_signals_strategy_version', table_name='signals')
    op.drop_index('ix_signals_status', table_name='signals')
    op.drop_index('ix_signals_direction', table_name='signals')
    op.drop_index('ix_signals_market', table_name='signals')
    op.drop_index('ix_signals_requested_by_user_id', table_name='signals')
    op.drop_table('signals')
    op.drop_index('ix_verification_requests_status', table_name='verification_requests')
    op.drop_index('ix_verification_requests_bcgame_user_id', table_name='verification_requests')
    op.drop_index('ix_verification_requests_user_id', table_name='verification_requests')
    op.drop_table('verification_requests')
    op.drop_index('ix_users_status', table_name='users')
    op.drop_index('ix_users_telegram_user_id', table_name='users')
    op.drop_table('users')

    bind = op.get_bind()
    for name in ('signalstatus', 'signaldirection', 'verificationstatus', 'userrole', 'userstatus'):
        sa.Enum(name=name).drop(bind, checkfirst=True)
