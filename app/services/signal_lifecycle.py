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

    def _timing_source(self, signal: Signal) -> str:
        return str(((signal.features_snapshot or {}).get('_bcgame_round') or {}).get('source') or 'AUTO_SYNC')

    async def activate_if_due(self, signal: Signal, now: datetime | None = None) -> Signal:
        if signal.status != SignalStatus.WAITING_ENTRY or signal.direction not in {SignalDirection.UP, SignalDirection.DOWN}:
            return signal
        if not signal.entry_at:
            return self._cancel(signal, 'Signal timing is incomplete.')

        current = now or datetime.now(timezone.utc)
        if current < signal.entry_at:
            return signal
        activation_deadline = signal.entry_at + timedelta(seconds=settings.signal_settlement_window_seconds)
        if current > activation_deadline:
            return self._cancel(signal, 'Estimated Start Rate reference window was missed.')

        source = self._timing_source(signal)
        if source == 'MANUAL_SYNC':
            # The player may already have placed the order. Do not cancel or
            # change the delivered direction after the fact. Capture only an
            # external reference price for later strategy evaluation.
            snapshot = await market_data_service.cache.get_snapshot(settings.analysis_pair, settings.market_data_max_age_seconds)
            if snapshot is None or not snapshot.fresh:
                return self._cancel(signal, 'Fresh external Start Rate reference was unavailable.')
            revalidated_direction = None
            revalidated_quality = None
        else:
            revalidated = await signal_intelligence_service.scan(settings.analysis_pair)
            if not revalidated.service_available:
                return self._cancel(signal, f'Start-rate revalidation unavailable: {revalidated.reason}')
            if revalidated.direction not in {SignalDirection.UP, SignalDirection.DOWN} or revalidated.direction != signal.direction:
                return self._cancel(signal, 'Direction was invalidated before Start Rate.')
            snapshot = revalidated.market_snapshot
            if snapshot is None or not snapshot.fresh:
                return self._cancel(signal, 'Fresh external reference data was unavailable at Start Rate time.')
            revalidated_direction = revalidated.direction.value
            revalidated_quality = revalidated.quality

        signal.reference_entry_price = snapshot.price
        signal.status = SignalStatus.ACTIVE
        feature_data = dict(signal.features_snapshot or {})
        market_meta = dict(feature_data.get('_market') or {})
        market_meta.update({
            'activated_at': current.isoformat(),
            'external_entry_event_time': snapshot.event_time.isoformat(),
            'external_entry_provider': snapshot.provider,
            'revalidated_direction': revalidated_direction,
            'revalidated_quality': revalidated_quality,
            'reference_only': True,
            'timing_source': source,
        })
        feature_data['_market'] = market_meta
        signal.features_snapshot = feature_data
        self.db.commit(); self.db.refresh(signal)
        return signal

    async def settle_if_due(self, signal: Signal, now: datetime | None = None) -> Signal:
        if signal.status != SignalStatus.ACTIVE or signal.direction not in {SignalDirection.UP, SignalDirection.DOWN}:
            return signal
        if signal.reference_entry_price is None or signal.expiry_at is None:
            return self._cancel(signal, 'Active signal is missing external entry reference or End Rate time.')

        current = now or datetime.now(timezone.utc)
        if current < signal.expiry_at:
            return signal

        deadline = signal.expiry_at + timedelta(seconds=settings.signal_settlement_window_seconds)
        snapshot = await market_data_service.cache.get_snapshot(settings.analysis_pair, max_age_seconds=settings.market_data_max_age_seconds)
        if snapshot is None or not snapshot.fresh or snapshot.event_time < signal.expiry_at:
            if current <= deadline:
                return signal
            return self._expire(signal, 'External reference at estimated End Rate time was unavailable.')
        if snapshot.event_time > deadline:
            return self._expire(signal, 'External End Rate reference arrived too late.')

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
            'external_expiry_event_time': snapshot.event_time.isoformat(),
            'external_expiry_provider': snapshot.provider,
            'reference_only': True,
        })
        feature_data['_market'] = market_meta
        signal.features_snapshot = feature_data
        signal.decision_reason = f'External-reference {signal.direction.value}: start={entry:.8f}, end={expiry:.8f}. BC.GAME Start/End Rate remains product truth.'
        self.db.commit(); self.db.refresh(signal)
        return signal

    def _cancel(self, signal: Signal, reason: str) -> Signal:
        signal.status = SignalStatus.CANCELLED
        signal.decision_reason = reason
        data = dict(signal.features_snapshot or {}); data['_cancelled_at'] = datetime.now(timezone.utc).isoformat(); signal.features_snapshot = data
        self.db.commit(); self.db.refresh(signal); return signal

    def _expire(self, signal: Signal, reason: str) -> Signal:
        signal.status = SignalStatus.EXPIRED
        signal.decision_reason = reason
        data = dict(signal.features_snapshot or {}); data['_expired_at'] = datetime.now(timezone.utc).isoformat(); signal.features_snapshot = data
        self.db.commit(); self.db.refresh(signal); return signal
