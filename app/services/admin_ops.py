from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import AuditLog, RuntimeSetting, User, UserStatus
from app.core.config import get_settings

settings = get_settings()


class AdminOpsService:
    SIGNALS_ENABLED_KEY = 'signals_enabled'

    def __init__(self, db: Session):
        self.db = db

    def get_bool(self, key: str, default: bool) -> bool:
        row = self.db.get(RuntimeSetting, key)
        if row is None:
            return default
        return row.value.lower() in {'1', 'true', 'yes', 'on'}

    def set_signals_enabled(self, enabled: bool, actor_telegram_id: int) -> bool:
        if enabled and settings.signal_mode.upper() != 'LIVE':
            raise ValueError('Signals cannot be enabled while SIGNAL_MODE is PAPER.')
        row = self.db.get(RuntimeSetting, self.SIGNALS_ENABLED_KEY)
        if row is None:
            row = RuntimeSetting(key=self.SIGNALS_ENABLED_KEY, value='true' if enabled else 'false')
            self.db.add(row)
        else:
            row.value = 'true' if enabled else 'false'
        row.updated_by = actor_telegram_id
        self._audit(actor_telegram_id, 'SIGNALS_ENABLED_CHANGED', 'system', {'enabled': enabled})
        self.db.commit()
        return enabled

    def suspend_user(self, user_id: int, actor_telegram_id: int) -> User:
        user = self.db.get(User, user_id)
        if user is None:
            raise ValueError('user not found')
        user.status = UserStatus.SUSPENDED
        self._audit(actor_telegram_id, 'USER_SUSPENDED', f'user:{user.id}', {'telegram_user_id': user.telegram_user_id})
        self.db.commit()
        self.db.refresh(user)
        return user

    def restore_user(self, user_id: int, actor_telegram_id: int) -> User:
        user = self.db.get(User, user_id)
        if user is None:
            raise ValueError('user not found')
        if user.approved_at is None:
            raise ValueError('only previously approved users can be restored')
        user.status = UserStatus.APPROVED
        self._audit(actor_telegram_id, 'USER_RESTORED', f'user:{user.id}', {'telegram_user_id': user.telegram_user_id})
        self.db.commit()
        self.db.refresh(user)
        return user

    def _audit(self, actor: int | None, action: str, target: str | None, details: dict | None = None) -> None:
        self.db.add(AuditLog(actor_telegram_id=actor, action=action, target=target, details=details))
