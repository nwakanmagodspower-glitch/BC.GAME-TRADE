from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Signal, SignalDirection, SignalStatus
from app.services.market_data import market_data_service

settings = get_settings()


class SignalLifecycleService:
    def __init__(self, db: Session): self.db = db

    async def activate_if_due(self, signal: Signal, now: datetime | None = None) -> Signal:
        if signal.status != SignalStatus.WAITING_ENTRY: return signal
        if signal.direction not in {SignalDirection.UP, SignalDirection.DOWN}: return signal
        if not signal.entry_window_start or not signal.entry_window_end: return self._cancel(signal, 'Signal timing is incomplete.')
        current = now or datetime.now(timezone.utc)
        if current < signal.entry_window_start: return signal
        if current > signal.entry_window_end: return self._cancel(signal, 'Entry window expired before activation.')
        snapshot = await market_data_service.cache.get_snapshot(signal.market, max_age_seconds=settings.market_data_max_age_seconds)
        if snapshot is None or not snapshot.fresh: return self._cancel(signal, 'Fresh market data was unavailable at entry.')

        signal.reference_entry_price = snapshot.price
        signal.status = SignalStatus.ACTIVE
        feature_data = dict(signal.features_snapshot or {})
        market_meta = dict(feature_data.get('_market') or {})
        market_meta.update({'activated_at': current.isoformat(), 'entry_event_time': snapshot.event_time.isoformat(), 'entry_provider': snapshot.provider})
        feature_data['_market'] = market_meta; signal.features_snapshot = feature_data
        self.db.commit(); self.db.refresh(signal); return signal

    async def settle_if_due(self, signal: Signal, now: datetime | None = None) -> Signal:
        if signal.status != SignalStatus.ACTIVE: return signal
        if signal.direction not in {SignalDirection.UP, SignalDirection.DOWN}: return signal
        if signal.reference_entry_price is None or signal.expiry_at is None: return self._cancel(signal, 'Active signal is missing entry price or expiry time.')
        current = now or datetime.now(timezone.utc)
        if current < signal.expiry_at: return signal
        snapshot = await market_data_service.cache.get_snapshot(signal.market, max_age_seconds=settings.market_data_max_age_seconds)
        if snapshot is None or not snapshot.fresh:
            signal.decision_reason = 'Settlement delayed: fresh market data unavailable.'; self.db.commit(); self.db.refresh(signal); return signal

        signal.reference_expiry_price = snapshot.price
        entry = signal.reference_entry_price; expiry = signal.reference_expiry_price
        if expiry == entry: signal.status = SignalStatus.TIE
        elif signal.direction == SignalDirection.UP: signal.status = SignalStatus.WIN if expiry > entry else SignalStatus.LOSS
        else: signal.status = SignalStatus.WIN if expiry < entry else SignalStatus.LOSS

        feature_data = dict(signal.features_snapshot or {})
        market_meta = dict(feature_data.get('_market') or {})
        market_meta.update({'settled_at': current.isoformat(), 'expiry_event_time': snapshot.event_time.isoformat(), 'expiry_provider': snapshot.provider})
        feature_data['_market'] = market_meta; signal.features_snapshot = feature_data
        signal.decision_reason = f'Settled {signal.direction.value}: entry={entry:.8f}, expiry={expiry:.8f}.'
        self.db.commit(); self.db.refresh(signal); return signal

    def _cancel(self, signal: Signal, reason: str) -> Signal:
        signal.status = SignalStatus.CANCELLED; signal.decision_reason = reason
        feature_data = dict(signal.features_snapshot or {}); feature_data['_cancelled_at'] = datetime.now(timezone.utc).isoformat(); signal.features_snapshot = feature_data
        self.db.commit(); self.db.refresh(signal); return signal
