from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Signal, SignalDirection, SignalStatus
from app.services.market_data import market_data_service
from app.services.signal_intelligence import signal_intelligence_service

settings = get_settings()


class SignalLifecycleService:
    def __init__(self, db: Session):
        self.db = db

    async def activate_if_due(self, signal: Signal, now: datetime | None = None) -> Signal:
        if signal.status != SignalStatus.WAITING_ENTRY:
            return signal
        if signal.direction not in {SignalDirection.UP, SignalDirection.DOWN}:
            return signal
        if not signal.entry_at or not signal.entry_window_end:
            return self._cancel(signal, 'Signal timing is incomplete.')

        current = now or datetime.now(timezone.utc)
        # Never activate before the planned synchronized entry timestamp.
        if current < signal.entry_at:
            return signal
        if current > signal.entry_window_end:
            return self._cancel(signal, 'Entry window expired before activation.')

        # Re-run the same V1 intelligence immediately before activation. A stale,
        # unavailable, NO_TRADE or opposite-direction state invalidates the earlier
        # candidate rather than allowing an outdated signal to become active.
        revalidated = await signal_intelligence_service.scan(signal.market)
        if not revalidated.service_available:
            return self._cancel(signal, f'Entry revalidation unavailable: {revalidated.reason}')
        if revalidated.direction not in {SignalDirection.UP, SignalDirection.DOWN}:
            return self._cancel(signal, f'Entry revalidation returned {revalidated.direction.value}.')
        if revalidated.direction != signal.direction:
            return self._cancel(signal, f'Entry direction changed from {signal.direction.value} to {revalidated.direction.value}.')
        snapshot = revalidated.market_snapshot
        if snapshot is None or not snapshot.fresh:
            return self._cancel(signal, 'Fresh market data was unavailable at entry.')

        signal.reference_entry_price = snapshot.price
        signal.status = SignalStatus.ACTIVE
        feature_data = dict(signal.features_snapshot or {})
        market_meta = dict(feature_data.get('_market') or {})
        market_meta.update({
            'activated_at': current.isoformat(),
            'entry_event_time': snapshot.event_time.isoformat(),
            'entry_provider': snapshot.provider,
            'revalidated_direction': revalidated.direction.value,
            'revalidated_quality': revalidated.quality,
        })
        feature_data['_market'] = market_meta
        signal.features_snapshot = feature_data
        self.db.commit()
        self.db.refresh(signal)
        return signal

    async def settle_if_due(self, signal: Signal, now: datetime | None = None) -> Signal:
        if signal.status != SignalStatus.ACTIVE:
            return signal
        if signal.direction not in {SignalDirection.UP, SignalDirection.DOWN}:
            return signal
        if signal.reference_entry_price is None or signal.expiry_at is None:
            return self._cancel(signal, 'Active signal is missing entry price or expiry time.')

        current = now or datetime.now(timezone.utc)
        if current < signal.expiry_at:
            return signal

        settlement_deadline = signal.expiry_at + timedelta(seconds=settings.signal_settlement_window_seconds)
        snapshot = await market_data_service.cache.get_snapshot(
            signal.market, max_age_seconds=settings.market_data_max_age_seconds
        )

        # Settlement must use a market event at/after the intended expiry and only
        # inside the small configured settlement window. If the worker/feed cannot
        # capture such a reference, preserve the signal as unresolved/EXPIRED
        # instead of assigning WIN/LOSS from a materially late price.
        if snapshot is None or not snapshot.fresh or snapshot.event_time < signal.expiry_at:
            if current <= settlement_deadline:
                return signal
            return self._expire(signal, 'Exact expiry reference was unavailable inside the settlement window.')
        if snapshot.event_time > settlement_deadline:
            return self._expire(signal, 'Expiry reference arrived too late for reliable settlement.')

        signal.reference_expiry_price = snapshot.price
        entry = signal.reference_entry_price
        expiry = signal.reference_expiry_price
        if expiry == entry:
            signal.status = SignalStatus.TIE
        elif signal.direction == SignalDirection.UP:
            signal.status = SignalStatus.WIN if expiry > entry else SignalStatus.LOSS
        else:
            signal.status = SignalStatus.WIN if expiry < entry else SignalStatus.LOSS

        feature_data = dict(signal.features_snapshot or {})
        market_meta = dict(feature_data.get('_market') or {})
        market_meta.update({
            'settled_at': current.isoformat(),
            'expiry_event_time': snapshot.event_time.isoformat(),
            'expiry_provider': snapshot.provider,
        })
        feature_data['_market'] = market_meta
        signal.features_snapshot = feature_data
        signal.decision_reason = f'Settled {signal.direction.value}: entry={entry:.8f}, expiry={expiry:.8f}.'
        self.db.commit()
        self.db.refresh(signal)
        return signal

    def _cancel(self, signal: Signal, reason: str) -> Signal:
        signal.status = SignalStatus.CANCELLED
        signal.decision_reason = reason
        feature_data = dict(signal.features_snapshot or {})
        feature_data['_cancelled_at'] = datetime.now(timezone.utc).isoformat()
        signal.features_snapshot = feature_data
        self.db.commit()
        self.db.refresh(signal)
        return signal

    def _expire(self, signal: Signal, reason: str) -> Signal:
        signal.status = SignalStatus.EXPIRED
        signal.decision_reason = reason
        feature_data = dict(signal.features_snapshot or {})
        feature_data['_expired_at'] = datetime.now(timezone.utc).isoformat()
        signal.features_snapshot = feature_data
        self.db.commit()
        self.db.refresh(signal)
        return signal
