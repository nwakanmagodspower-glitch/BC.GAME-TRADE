from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Signal, SignalDirection, SignalStatus
from app.services.market_data import market_data_service

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
            return self._expire(signal, 'Delivered signal has incomplete timing metadata; direction remains unchanged.')

        current = now or datetime.now(timezone.utc)
        if current < signal.entry_at:
            return signal

        source = self._timing_source(signal)
        activation_deadline = signal.entry_at + timedelta(seconds=settings.signal_settlement_window_seconds)
        if current > activation_deadline:
            return self._expire(
                signal,
                'External Start Rate reference window was missed; the delivered signal direction remains unchanged.',
            )

        # IMPORTANT: once a directional signal has been delivered to Telegram, the
        # direction is immutable. A user may already have acted on it in BCGAME.
        # Never run a second strategy decision here and never cancel the delivered
        # signal because market conditions changed after dispatch. Lifecycle work
        # from this point onward is reference/result bookkeeping only.
        snapshot = await market_data_service.cache.get_snapshot(
            settings.analysis_pair,
            settings.market_data_max_age_seconds,
        )
        if snapshot is None or not snapshot.fresh:
            return self._expire(
                signal,
                'External Start Rate reference was unavailable; the delivered signal direction remains unchanged.',
            )

        signal.reference_entry_price = snapshot.price
        signal.status = SignalStatus.ACTIVE
        feature_data = dict(signal.features_snapshot or {})
        market_meta = dict(feature_data.get('_market') or {})
        market_meta.update({
            'activated_at': current.isoformat(),
            'external_entry_event_time': snapshot.event_time.isoformat(),
            'external_entry_provider': snapshot.provider,
            'revalidated_direction': None,
            'revalidated_quality': None,
            'direction_immutable_after_delivery': True,
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
            return self._expire(signal, 'Active signal is missing an external reference; no result was guessed.')

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

        # BCGAME's supplied rule is binary: UP wins only when End > Start;
        # otherwise DOWN wins. Equality therefore belongs to DOWN, not TIE.
        if signal.direction == SignalDirection.UP:
            signal.status = SignalStatus.WIN if expiry > entry else SignalStatus.LOSS
        else:
            signal.status = SignalStatus.WIN if expiry <= entry else SignalStatus.LOSS

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
        signal.status_reason = f'External-reference {signal.direction.value}: start={entry:.8f}, end={expiry:.8f}. BCGAME Start/End Rate remains product truth.'
        self.db.commit(); self.db.refresh(signal)
        return signal

    def _cancel(self, signal: Signal, reason: str) -> Signal:
        # Kept for compatibility with older records/callers. New delivered signals
        # should never reach this path after Telegram dispatch.
        signal.status = SignalStatus.CANCELLED
        signal.status_reason = reason
        data = dict(signal.features_snapshot or {}); data['_cancelled_at'] = datetime.now(timezone.utc).isoformat(); signal.features_snapshot = data
        self.db.commit(); self.db.refresh(signal); return signal

    def _expire(self, signal: Signal, reason: str) -> Signal:
        signal.status = SignalStatus.EXPIRED
        signal.status_reason = reason
        data = dict(signal.features_snapshot or {}); data['_expired_at'] = datetime.now(timezone.utc).isoformat(); signal.features_snapshot = data
        self.db.commit(); self.db.refresh(signal); return signal
