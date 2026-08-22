from __future__ import annotations

from telegram import Bot
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Signal, SignalNotification, SignalStatus, User, UserStatus, utcnow

settings = get_settings()


class SignalNotificationService:
    def __init__(self, db: Session):
        self.db = db

    def _timing_source(self, signal: Signal) -> str:
        return str(((signal.features_snapshot or {}).get('_bcgame_round') or {}).get('source') or 'AUTO_SYNC')

    async def notify_status(self, signal: Signal) -> bool:
        if not settings.telegram_bot_token or signal.requested_by_user_id is None:
            return False
        if signal.status == SignalStatus.CANCELLED:
            return False
        if signal.status not in {
            SignalStatus.ACTIVE, SignalStatus.EXPIRED,
            SignalStatus.WIN, SignalStatus.LOSS, SignalStatus.TIE,
        }:
            return False
        if self._timing_source(signal) == 'MANUAL_SYNC':
            return False

        user = self.db.get(User, signal.requested_by_user_id)
        if user is None or user.status != UserStatus.APPROVED or user.is_blocked:
            return False

        event = signal.status.value
        record = self.db.scalar(select(SignalNotification).where(
            SignalNotification.signal_id == signal.id,
            SignalNotification.event == event,
        ))
        if record is not None and record.sent_at is not None:
            return False
        if record is None:
            record = SignalNotification(signal_id=signal.id, event=event, created_at=utcnow())
            self.db.add(record); self.db.commit(); self.db.refresh(record)

        text = self._render(signal)
        record.attempts += 1
        try:
            async with Bot(settings.telegram_bot_token) as bot:
                await bot.send_message(user.telegram_user_id, text)
            record.sent_at = utcnow(); record.last_error = None; self.db.commit(); return True
        except Exception as exc:
            record.last_error = f'{type(exc).__name__}: {exc}'; self.db.commit(); return False

    def _render(self, signal: Signal) -> str:
        mode = settings.signal_mode.upper()

        if signal.status == SignalStatus.ACTIVE:
            if mode == 'PAPER':
                return (
                    '🧪 PAPER ROUND LOCKED\n\n'
                    f'{signal.direction.value} • BTC/USD • 5s\n\n'
                    'The entry window is closed. Waiting for the reference result.'
                )
            icon = '🟢' if signal.direction.value == 'UP' else '🔴'
            return (
                '🔒 SIGNAL LOCKED\n\n'
                f'{icon} {signal.direction.value} • BTC/USD • 5s\n\n'
                'The delivered direction is final for this round.\n'
                '⏳ Checking the reference result...'
            )

        if signal.status == SignalStatus.EXPIRED:
            prefix = '🧪 PAPER RESULT UNRESOLVED' if mode == 'PAPER' else '⚠️ RESULT UNAVAILABLE'
            return (
                f'{prefix}\n\n'
                'The internal reference result could not be confirmed safely. '
                'The original signal direction has not changed.\n\n'
                'Use BCGAME Start Rate and End Rate as the result source for this round.'
            )

        icon = '✅' if signal.status == SignalStatus.WIN else ('❌' if signal.status == SignalStatus.LOSS else '➖')
        prefix = '🧪 PAPER ' if mode == 'PAPER' else ''
        direction_icon = '🟢' if signal.direction.value == 'UP' else ('🔴' if signal.direction.value == 'DOWN' else '⚪')
        return (
            f'{prefix}{icon} ROUND RESULT: {signal.status.value}\n\n'
            f'{direction_icon} {signal.direction.value} • BTC/USD • 5s\n\n'
            'Round complete. Use the main menu whenever you want another market scan.'
        )
