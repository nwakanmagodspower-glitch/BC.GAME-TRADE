from __future__ import annotations

from telegram import Bot
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Signal, SignalNotification, SignalStatus, User, utcnow

settings = get_settings()


class SignalNotificationService:
    def __init__(self, db: Session):
        self.db = db

    async def notify_status(self, signal: Signal) -> bool:
        if not settings.telegram_bot_token or signal.requested_by_user_id is None:
            return False
        if signal.status not in {
            SignalStatus.ACTIVE, SignalStatus.CANCELLED, SignalStatus.EXPIRED,
            SignalStatus.WIN, SignalStatus.LOSS, SignalStatus.TIE,
        }:
            return False

        user = self.db.get(User, signal.requested_by_user_id)
        if user is None or user.is_blocked:
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
            end_time = signal.expiry_at.strftime('%H:%M:%S UTC') if signal.expiry_at else 'Pending'
            if mode == 'PAPER':
                return (
                    '🧪 PAPER ROUND STARTED\n\n'
                    'BTC/USD — BC.GAME 5s UP/DOWN\n'
                    f'Model direction: {signal.direction.value}\n'
                    f'5-second End Rate time: {end_time}\n\n'
                    'BC.GAME order window is already closed. Validation only.'
                )
            return (
                '🔒 ROUND LOCKED — 5s MEASUREMENT STARTED\n\n'
                f'Direction: {signal.direction.value}\n'
                f'End Rate time: {end_time}\n\n'
                'Do not attempt a late order. Wait for the result.'
            )

        if signal.status == SignalStatus.CANCELLED:
            prefix = '🧪 PAPER SIGNAL CANCELLED' if mode == 'PAPER' else '⚠️ SIGNAL CANCELLED'
            return f'{prefix}\n\n{signal.decision_reason or "The next-round setup was invalidated before Start Rate."}'

        if signal.status == SignalStatus.EXPIRED:
            prefix = '🧪 PAPER RESULT UNRESOLVED' if mode == 'PAPER' else '⚠️ RESULT UNRESOLVED'
            return (
                f'{prefix}\n\n'
                'A trustworthy result reference was not captured inside the required window, so the system did not guess a WIN/LOSS.\n\n'
                f'{signal.decision_reason or "Result source unavailable."}'
            )

        start = f'{signal.reference_entry_price:,.5f}' if signal.reference_entry_price is not None else 'Unavailable'
        end = f'{signal.reference_expiry_price:,.5f}' if signal.reference_expiry_price is not None else 'Unavailable'
        icon = '✅' if signal.status == SignalStatus.WIN else ('❌' if signal.status == SignalStatus.LOSS else '➖')
        prefix = '🧪 PAPER ' if mode == 'PAPER' else ''
        return (
            f'{prefix}{icon} 5s SIGNAL RESULT — {signal.status.value}\n\n'
            f'Direction: {signal.direction.value}\n'
            f'External start reference: {start}\n'
            f'External end reference: {end}\n\n'
            'BC.GAME Start Rate / End Rate is the product truth. External-reference results remain diagnostic until BC.GAME round-result ingestion is verified.'
        )
