from alembic import op
import sqlalchemy as sa

revision = '0006_bcgame_rounds'
down_revision = '0005_admin_broadcast_ops'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'bcgame_rounds',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('external_round_id', sa.String(length=120), nullable=True),
        sa.Column('game_market', sa.String(length=40), nullable=False, server_default='BTC/USD'),
        sa.Column('duration_seconds', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('stake_band', sa.String(length=40), nullable=False, server_default='1-50'),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('order_closes_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('start_rate_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_rate_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('start_rate', sa.Float(), nullable=True),
        sa.Column('end_rate', sa.Float(), nullable=True),
        sa.Column('actual_direction', sa.String(length=10), nullable=True),
        sa.Column('up_payout_pct', sa.Float(), nullable=True),
        sa.Column('down_payout_pct', sa.Float(), nullable=True),
        sa.Column('up_pool_amount', sa.Float(), nullable=True),
        sa.Column('down_pool_amount', sa.Float(), nullable=True),
        sa.Column('up_players', sa.Integer(), nullable=True),
        sa.Column('down_players', sa.Integer(), nullable=True),
        sa.Column('source', sa.String(length=80), nullable=True),
        sa.Column('raw_metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('external_round_id', name='uq_bcgame_rounds_external_round_id'),
    )
    op.create_index('ix_bcgame_rounds_external_round_id', 'bcgame_rounds', ['external_round_id'])
    op.create_index('ix_bcgame_rounds_game_market', 'bcgame_rounds', ['game_market'])
    op.create_index('ix_bcgame_rounds_stake_band', 'bcgame_rounds', ['stake_band'])
    op.create_index('ix_bcgame_rounds_observed_at', 'bcgame_rounds', ['observed_at'])
    op.create_index('ix_bcgame_rounds_order_closes_at', 'bcgame_rounds', ['order_closes_at'])
    op.create_index('ix_bcgame_rounds_actual_direction', 'bcgame_rounds', ['actual_direction'])

    op.add_column('signals', sa.Column('bcgame_round_id', sa.Integer(), sa.ForeignKey('bcgame_rounds.id'), nullable=True))
    op.create_index('ix_signals_bcgame_round_id', 'signals', ['bcgame_round_id'])


def downgrade():
    op.drop_index('ix_signals_bcgame_round_id', table_name='signals')
    op.drop_column('signals', 'bcgame_round_id')
    op.drop_table('bcgame_rounds')
