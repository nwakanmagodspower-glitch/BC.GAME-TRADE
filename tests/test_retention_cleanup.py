from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.entities import Broadcast, BroadcastDelivery, BroadcastStatus, SignalNotification, User, UserStatus
from app.models.webhook import TelegramUpdateReceipt
from app.services import retention_cleanup as cleanup_module
from app.services.retention_cleanup import RetentionCleanupService


def test_cleanup_deletes_only_temporary_records_older_than_10_days(monkeypatch):
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(cleanup_module, 'SessionLocal', Session)

    now = datetime.now(timezone.utc)
    old = now - timedelta(days=11)
    recent = now - timedelta(days=9)

    with Session() as db:
        user = User(telegram_user_id=1001, status=UserStatus.APPROVED)
        db.add(user); db.flush()

        db.add_all([
            TelegramUpdateReceipt(update_id=1, received_at=old),
            TelegramUpdateReceipt(update_id=2, received_at=recent),
            SignalNotification(signal_id=999, event='OLD_TEST', created_at=old),
        ])
        # SQLite tests do not enforce the notification FK unless configured.
        broadcast = Broadcast(message='test', created_by=1, status=BroadcastStatus.COMPLETE, completed_at=old)
        db.add(broadcast); db.flush()
        db.add(BroadcastDelivery(broadcast_id=broadcast.id, user_id=user.id))
        db.commit()

    service = RetentionCleanupService(retention_days=10, interval_seconds=86400)
    result = service.cleanup_once(now=now)

    assert result.webhook_receipts == 1
    assert result.signal_notifications == 1
    assert result.broadcast_deliveries == 1

    with Session() as db:
        receipts = db.scalars(select(TelegramUpdateReceipt).order_by(TelegramUpdateReceipt.update_id)).all()
        assert [row.update_id for row in receipts] == [2]
        assert db.scalar(select(Broadcast)) is not None  # summary is retained
        assert db.scalar(select(User).where(User.telegram_user_id == 1001)) is not None
