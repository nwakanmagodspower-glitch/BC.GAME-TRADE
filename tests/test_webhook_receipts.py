from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.services.webhook_receipts import WebhookReceiptService


def test_receipts_only_deduplicate_successful_updates_and_retry_failures():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    now = datetime.now(timezone.utc)

    with Session() as db:
        service = WebhookReceiptService(db)
        assert service.claim(10, now=now).claimed
        in_progress = service.claim(10, now=now)
        assert in_progress.in_progress and not in_progress.duplicate
        service.fail(10, 'handler_failed')
        assert service.claim(10, now=now).claimed
        service.succeed(10)
        duplicate = service.claim(10, now=now)
        assert duplicate.duplicate and not duplicate.claimed
