from __future__ import annotations

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
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
        record = self.db.scalar(select(SignalNotification).where(SignalNotification.signal_id == signal.id, SignalNotification.event == event))
        if record is not None and record.sent_at is not None:
            return False
        if record is None:
            record = SignalNotification(signal_id=signal.id, event=event, created_at=utcnow())
            self.db.add(record); self.db.commit(); self.db.refresh(record)

        text, keyboard = self._render(signal)
        record.attempts += 1
        try:
            async with Bot(settings.telegram_bot_token) as bot:
                await bot.send_message(user.telegram_user_id, text, reply_markup=keyboard)
            record.sent_at = utcnow(); record.last_error = None; self.db.commit(); return True
        except Exception as exc:
            record.last_error = f'{type(exc).__name__}: {exc}'; self.db.commit(); return False

    def _render(self, signal: Signal):
        mode = settings.signal_mode.upper()
        if signal.status == SignalStatus.ACTIVE:
            expiry = signal.expiry_at.strftime('%H:%M:%S UTC') if signal.expiry_at else 'Pending'
            price = f'{signal.reference_entry_price:,.2f}' if signal.reference_entry_price is not None else 'Unavailable'
            if mode == 'PAPER':
                text = (
                    '🧪 PAPER ENTRY MARKER\n\n'
                    'BTC/USDT — BC.GAME UP/DOWN\n'
                    f'Direction: {signal.direction.value}\n'
                    f'Reference entry: {price}\n'
                    f'Expiry: {expiry}\n\n'
                    'Validation only — do not place a trade from this message.'
                )
                return text, None

            text = (
                '🚨 ENTER NOW\n\n'
                'BTC/USDT — BC.GAME UP/DOWN\n'
                f'Direction: {signal.direction.value}\n'
                f'Reference entry: {price}\n'
                f'Expiry: {expiry}'
            )
            rows = []
            if settings.bcgame_updown_url:
                rows.append([InlineKeyboardButton('🚀 Open BC.GAME Up/Down', url=settings.bcgame_updown_url)])
            return text, InlineKeyboardMarkup(rows) if rows else None

        if signal.status == SignalStatus.CANCELLED:
            prefix = '🧪 PAPER SIGNAL CANCELLED' if mode == 'PAPER' else '⚠️ SIGNAL CANCELLED'
            return (f'{prefix}\n\nDo not enter this signal. {signal.decision_reason or "Market conditions or timing invalidated the setup."}', None)

        if signal.status == SignalStatus.EXPIRED:
            prefix = '🧪 PAPER RESULT UNRESOLVED' if mode == 'PAPER' else '⚠️ RESULT UNRESOLVED'
            return (
                f'{prefix}\n\n'
                'The system could not capture a reliable reference price inside the exact expiry window, '
                'so no WIN/LOSS/TIE result was assigned.\n\n'
                f'{signal.decision_reason or "Exact settlement reference unavailable."}',
                None,
            )

        entry = f'{signal.reference_entry_price:,.2f}' if signal.reference_entry_price is not None else 'Unavailable'
        expiry = f'{signal.reference_expiry_price:,.2f}' if signal.reference_expiry_price is not None else 'Unavailable'
        icon = '✅' if signal.status == SignalStatus.WIN else ('❌' if signal.status == SignalStatus.LOSS else '➖')
        mode_prefix = '🧪 PAPER ' if mode == 'PAPER' else ''
        text = (
            f'{mode_prefix}{icon} SIGNAL RESULT — {signal.status.value}\n\n'
            f'Direction: {signal.direction.value}\n'
            f'Entry reference: {entry}\n'
            f'Expiry reference: {expiry}\n\n'
            'Result shown is based on the configured external reference feed until '
            'BC.GAME settlement matching is fully verified.'
        )
        return text, None
