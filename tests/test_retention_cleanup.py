from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.entities import (
    BCGameRound, Broadcast, BroadcastDelivery, BroadcastStatus, Signal, SignalDirection,
    SignalNotification, SignalStatus, User, UserStatus,
)
from app.models.webhook import TelegramUpdateReceipt
from app.services import retention_cleanup as cleanup_module
from app.services.retention_cleanup import RetentionCleanupService


def test_cleanup_deletes_technical_and_signal_records_older_than_10_days(monkeypatch):
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(cleanup_module, 'SessionLocal', Session)

    now = datetime.now(timezone.utc)
    old = now - timedelta(days=11)
    recent = now - timedelta(days=9)

    with Session() as db:
        user = User(telegram_user_id=1001, status=UserStatus.APPROVED)
        db.add(user)
        db.flush()

        old_round = BCGameRound(
            external_round_id='old-round', observed_at=old,
            order_closes_at=old, start_rate_at=old, end_rate_at=old,
        )
        recent_round = BCGameRound(
            external_round_id='recent-round', observed_at=recent,
            order_closes_at=recent, start_rate_at=recent, end_rate_at=recent,
        )
        db.add_all([old_round, recent_round])
        db.flush()

        old_signal = Signal(
            requested_by_user_id=user.id,
            bcgame_round_id=old_round.id,
            market='BTC/USD',
            product='BC_UPDOWN_5S',
            direction=SignalDirection.UP,
            status=SignalStatus.WIN,
            strategy_version='BTC_UPDOWN_5S_V1.1',
            created_at=old,
        )
        recent_signal = Signal(
            requested_by_user_id=user.id,
            market='BTC/USD',
            product='BC_UPDOWN_5S',
            direction=SignalDirection.DOWN,
            status=SignalStatus.LOSS,
            strategy_version='BTC_UPDOWN_5S_V1.1',
            created_at=recent,
        )
        db.add_all([old_signal, recent_signal])
        db.flush()

        db.add_all([
            TelegramUpdateReceipt(update_id=1, received_at=old),
            TelegramUpdateReceipt(update_id=2, received_at=recent),
            SignalNotification(signal_id=old_signal.id, event='OLD_TEST', created_at=old),
        ])
        broadcast = Broadcast(message='test', created_by=1, status=BroadcastStatus.COMPLETE, completed_at=old)
        db.add(broadcast)
        db.flush()
        db.add(BroadcastDelivery(broadcast_id=broadcast.id, user_id=user.id))
        db.commit()

    service = RetentionCleanupService(retention_days=10, interval_seconds=86400)
    result = service.cleanup_once(now=now)

    assert result.webhook_receipts == 1
    assert result.signal_notifications == 1
    assert result.signals == 1
    assert result.bcgame_rounds == 1
    assert result.broadcast_deliveries == 1

    with Session() as db:
        receipts = db.scalars(select(TelegramUpdateReceipt).order_by(TelegramUpdateReceipt.update_id)).all()
        assert [row.update_id for row in receipts] == [2]
        signals = db.scalars(select(Signal).order_by(Signal.id)).all()
        assert len(signals) == 1
        assert signals[0].created_at.replace(tzinfo=timezone.utc) == recent
        rounds = db.scalars(select(BCGameRound).order_by(BCGameRound.id)).all()
        assert [row.external_round_id for row in rounds] == ['recent-round']
        assert db.scalar(select(Broadcast)) is not None
        assert db.scalar(select(User).where(User.telegram_user_id == 1001)) is not None
