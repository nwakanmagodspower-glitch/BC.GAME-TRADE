from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import (
    AuditLog, Broadcast, BroadcastDelivery, BroadcastStatus, DeliveryStatus,
    User, UserStatus, utcnow,
)


class BroadcastService:
    def __init__(self, db: Session):
        self.db = db

    def create_draft(self, message: str, actor_telegram_id: int) -> Broadcast:
        message = message.strip()
        if not message:
            raise ValueError('Broadcast message cannot be empty.')
        if len(message) > 4000:
            raise ValueError('Broadcast message is too long.')
        broadcast = Broadcast(message=message, created_by=actor_telegram_id)
        self.db.add(broadcast)
        self.db.add(AuditLog(actor_telegram_id=actor_telegram_id, action='BROADCAST_DRAFT_CREATED'))
        self.db.commit(); self.db.refresh(broadcast)
        return broadcast

    def approved_recipient_count(self) -> int:
        return int(self.db.scalar(select(func.count(User.id)).where(User.status == UserStatus.APPROVED, User.is_blocked.is_(False))) or 0)

    def queue(self, broadcast_id: int, actor_telegram_id: int) -> Broadcast:
        broadcast = self.db.get(Broadcast, broadcast_id)
        if not broadcast or broadcast.status != BroadcastStatus.DRAFT:
            raise ValueError('Broadcast is not available for queueing.')
        users = self.db.scalars(select(User).where(User.status == UserStatus.APPROVED, User.is_blocked.is_(False))).all()
        for user in users:
            self.db.add(BroadcastDelivery(broadcast_id=broadcast.id, user_id=user.id))
        broadcast.recipient_count = len(users)
        broadcast.status = BroadcastStatus.QUEUED
        broadcast.queued_at = utcnow()
        self.db.add(AuditLog(actor_telegram_id=actor_telegram_id, action='BROADCAST_QUEUED', target=str(broadcast.id), details={'recipients': len(users)}))
        self.db.commit(); self.db.refresh(broadcast)
        return broadcast

    def cancel_draft(self, broadcast_id: int, actor_telegram_id: int) -> None:
        broadcast = self.db.get(Broadcast, broadcast_id)
        if not broadcast or broadcast.status != BroadcastStatus.DRAFT:
            raise ValueError('Only a draft broadcast can be cancelled.')
        self.db.delete(broadcast)
        self.db.add(AuditLog(actor_telegram_id=actor_telegram_id, action='BROADCAST_DRAFT_CANCELLED', target=str(broadcast_id)))
        self.db.commit()
