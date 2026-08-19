from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.webhook import TelegramUpdateReceipt

settings = get_settings()


@dataclass(frozen=True)
class ReceiptClaim:
    claimed: bool
    duplicate: bool = False
    in_progress: bool = False


class WebhookReceiptService:
    def __init__(self, db: Session):
        self.db = db

    def claim(self, update_id: int, now: datetime | None = None) -> ReceiptClaim:
        current = now or datetime.now(timezone.utc)
        try:
            self.db.execute(
                insert(TelegramUpdateReceipt).values(
                    update_id=update_id,
                    received_at=current,
                    status='PROCESSING',
                    attempts=1,
                )
            )
            self.db.commit()
            return ReceiptClaim(claimed=True)
        except IntegrityError:
            self.db.rollback()
        receipt = self.db.get(TelegramUpdateReceipt, update_id)
        if receipt is None:
            return ReceiptClaim(claimed=False, in_progress=True)
        if receipt.status == 'SUCCEEDED':
            return ReceiptClaim(claimed=False, duplicate=True)

        received_at = receipt.received_at
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=timezone.utc)
        stale_before = current - timedelta(seconds=settings.telegram_update_processing_timeout_seconds)
        if receipt.status == 'PROCESSING' and received_at >= stale_before:
            return ReceiptClaim(claimed=False, in_progress=True)

        receipt.status = 'PROCESSING'
        receipt.received_at = current
        receipt.attempts += 1
        receipt.last_error = None
        receipt.completed_at = None
        self.db.commit()
        return ReceiptClaim(claimed=True)

    def succeed(self, update_id: int) -> None:
        receipt = self.db.get(TelegramUpdateReceipt, update_id)
        if receipt is None:
            return
        receipt.status = 'SUCCEEDED'
        receipt.completed_at = datetime.now(timezone.utc)
        receipt.last_error = None
        self.db.commit()

    def fail(self, update_id: int, error_code: str) -> None:
        receipt = self.db.get(TelegramUpdateReceipt, update_id)
        if receipt is None:
            return
        receipt.status = 'FAILED'
        receipt.completed_at = datetime.now(timezone.utc)
        receipt.last_error = error_code[:200]
        self.db.commit()
