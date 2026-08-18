"""add signal notifications

Revision ID: 0004_signal_notifications
Revises: 0003_telegram_update_receipts
"""

from alembic import op
import sqlalchemy as sa

revision = '0004_signal_notifications'
down_revision = '0003_telegram_update_receipts'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'signal_notifications',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('signal_id', sa.Integer(), sa.ForeignKey('signals.id'), nullable=False),
        sa.Column('event', sa.String(length=40), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('signal_id', 'event', name='uq_signal_notification_event'),
    )
    op.create_index('ix_signal_notifications_signal_id', 'signal_notifications', ['signal_id'])
    op.create_index('ix_signal_notifications_event', 'signal_notifications', ['event'])


def downgrade():
    op.drop_index('ix_signal_notifications_event', table_name='signal_notifications')
    op.drop_index('ix_signal_notifications_signal_id', table_name='signal_notifications')
    op.drop_table('signal_notifications')
