"""harden webhook receipts and verification delivery

Revision ID: 0007_security_delivery_hardening
Revises: 0006_bcgame_rounds
"""

from alembic import op
import sqlalchemy as sa

revision = '0007_security_delivery_hardening'
down_revision = '0006_bcgame_rounds'
branch_labels = None
depends_on = None


def upgrade() -> None:
    verification_delivery_status = sa.Enum(
        'PENDING', 'SENDING', 'SENT', 'FAILED', name='verificationdeliverystatus'
    )
    verification_delivery_status.create(op.get_bind(), checkfirst=True)

    op.add_column('verification_requests', sa.Column('last_evidence_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('last_scan_requested_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('signals', sa.Column('status_reason', sa.Text(), nullable=True))

    op.add_column('telegram_update_receipts', sa.Column('status', sa.String(length=16), nullable=False, server_default='SUCCEEDED'))
    op.add_column('telegram_update_receipts', sa.Column('attempts', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('telegram_update_receipts', sa.Column('last_error', sa.Text(), nullable=True))
    op.add_column('telegram_update_receipts', sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_telegram_update_receipts_status', 'telegram_update_receipts', ['status'])

    op.create_table(
        'verification_deliveries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('verification_request_id', sa.Integer(), sa.ForeignKey('verification_requests.id'), nullable=False),
        sa.Column('status', verification_delivery_status, nullable=False, server_default='PENDING'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('verification_request_id', name='uq_verification_deliveries_request'),
    )
    op.create_index('ix_verification_deliveries_verification_request_id', 'verification_deliveries', ['verification_request_id'])
    op.create_index('ix_verification_deliveries_status', 'verification_deliveries', ['status'])
    op.create_index(
        'uq_signals_current_per_user',
        'signals',
        ['requested_by_user_id'],
        unique=True,
        postgresql_where=sa.text(
            "requested_by_user_id IS NOT NULL AND status IN ('WAITING_ENTRY', 'ACTIVE')"
        ),
        sqlite_where=sa.text(
            "requested_by_user_id IS NOT NULL AND status IN ('WAITING_ENTRY', 'ACTIVE')"
        ),
    )


def downgrade() -> None:
    op.drop_index('uq_signals_current_per_user', table_name='signals')
    op.drop_table('verification_deliveries')
    op.drop_index('ix_telegram_update_receipts_status', table_name='telegram_update_receipts')
    op.drop_column('telegram_update_receipts', 'completed_at')
    op.drop_column('telegram_update_receipts', 'last_error')
    op.drop_column('telegram_update_receipts', 'attempts')
    op.drop_column('telegram_update_receipts', 'status')
    op.drop_column('verification_requests', 'last_evidence_at')
    op.drop_column('users', 'last_scan_requested_at')
    op.drop_column('signals', 'status_reason')
    sa.Enum(name='verificationdeliverystatus').drop(op.get_bind(), checkfirst=True)
