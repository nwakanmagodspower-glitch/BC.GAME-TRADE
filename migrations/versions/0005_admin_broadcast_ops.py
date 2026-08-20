from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0005_admin_broadcast_ops'
down_revision = '0004_signal_notifications'
branch_labels = None
depends_on = None

BROADCAST_STATUS_VALUES = ('DRAFT', 'QUEUED', 'SENDING', 'COMPLETE', 'FAILED')
DELIVERY_STATUS_VALUES = ('PENDING', 'SENT', 'FAILED')


def _enum(bind, values: tuple[str, ...], name: str):
    if bind.dialect.name == 'postgresql':
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)
        return postgresql.ENUM(*values, name=name, create_type=False)
    return sa.Enum(*values, name=name)


def upgrade():
    bind = op.get_bind()
    broadcast_status = _enum(bind, BROADCAST_STATUS_VALUES, 'broadcaststatus')
    delivery_status = _enum(bind, DELIVERY_STATUS_VALUES, 'deliverystatus')

    op.add_column('broadcasts', sa.Column('status', broadcast_status, nullable=False, server_default='DRAFT'))
    op.add_column('broadcasts', sa.Column('queued_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('broadcasts', sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_broadcasts_status', 'broadcasts', ['status'])

    op.create_table(
        'broadcast_deliveries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('broadcast_id', sa.Integer(), sa.ForeignKey('broadcasts.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('status', delivery_status, nullable=False, server_default='PENDING'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('broadcast_id', 'user_id', name='uq_broadcast_delivery_user'),
    )
    op.create_index('ix_broadcast_deliveries_broadcast_id', 'broadcast_deliveries', ['broadcast_id'])
    op.create_index('ix_broadcast_deliveries_user_id', 'broadcast_deliveries', ['user_id'])
    op.create_index('ix_broadcast_deliveries_status', 'broadcast_deliveries', ['status'])

    op.create_table(
        'runtime_settings',
        sa.Column('key', sa.String(length=100), primary_key=True),
        sa.Column('value', sa.String(length=255), nullable=False),
        sa.Column('updated_by', sa.BigInteger(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('actor_telegram_id', sa.BigInteger(), nullable=True),
        sa.Column('action', sa.String(length=120), nullable=False),
        sa.Column('target', sa.String(length=255), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_audit_logs_actor_telegram_id', 'audit_logs', ['actor_telegram_id'])
    op.create_index('ix_audit_logs_action', 'audit_logs', ['action'])
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'])


def downgrade():
    bind = op.get_bind()
    op.drop_table('audit_logs')
    op.drop_table('runtime_settings')
    op.drop_table('broadcast_deliveries')
    op.drop_index('ix_broadcasts_status', table_name='broadcasts')
    op.drop_column('broadcasts', 'completed_at')
    op.drop_column('broadcasts', 'queued_at')
    op.drop_column('broadcasts', 'status')
    if bind.dialect.name == 'postgresql':
        postgresql.ENUM(*DELIVERY_STATUS_VALUES, name='deliverystatus').drop(bind, checkfirst=True)
        postgresql.ENUM(*BROADCAST_STATUS_VALUES, name='broadcaststatus').drop(bind, checkfirst=True)
    else:
        sa.Enum(*DELIVERY_STATUS_VALUES, name='deliverystatus').drop(bind, checkfirst=True)
        sa.Enum(*BROADCAST_STATUS_VALUES, name='broadcaststatus').drop(bind, checkfirst=True)
