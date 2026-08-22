from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.entities import Signal


class SignalNotificationService:
    """Telegram lifecycle notifications are intentionally disabled.

    Users receive the actionable scan response only. Internal signal lifecycle
    tracking can continue in the database for diagnostics and future authoritative
    settlement work, but ACTIVE/EXPIRED/WIN/LOSS/TIE/CANCELLED state changes must
    not create extra Telegram messages.
    """

    def __init__(self, db: Session):
        self.db = db

    async def notify_status(self, signal: Signal) -> bool:
        return False
