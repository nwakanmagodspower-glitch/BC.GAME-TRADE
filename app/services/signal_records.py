from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Signal, SignalDirection, SignalStatus, utcnow
from app.services.signal_intelligence import IntelligenceResult
from app.signals.timing import plan_timing

settings = get_settings()


class SignalRecordService:
    def __init__(self, db: Session):
        self.db = db

    def record_scan(self, result: IntelligenceResult, requested_by_user_id: int | None = None) -> Signal:
        is_trade = result.direction in {SignalDirection.UP, SignalDirection.DOWN}
        timing = None
        if is_trade:
            timing = plan_timing(
                expiry_seconds=settings.default_expiry_seconds,
                alignment_seconds=settings.signal_entry_alignment_seconds,
                entry_window_seconds=settings.signal_entry_window_seconds,
                minimum_lead_seconds=settings.signal_minimum_lead_seconds,
            )

        status = SignalStatus.WAITING_ENTRY if is_trade else SignalStatus.NO_TRADE
        feature_data = result.features.to_dict() if result.features is not None else {}
        if result.decision is not None:
            feature_data['_decision'] = {
                'quality': result.quality,
                'bull_score': result.decision.bull_score,
                'bear_score': result.decision.bear_score,
            }
        feature_data['_market'] = {
            'scan_price': result.reference_price,
            'provider': result.market_snapshot.provider if result.market_snapshot else None,
            'event_time': result.market_snapshot.event_time.isoformat() if result.market_snapshot else None,
        }

        signal = Signal(
            requested_by_user_id=requested_by_user_id,
            market=result.market,
            product='BC_UPDOWN',
            direction=result.direction,
            status=status,
            strategy_version=settings.strategy_version,
            confidence=None,
            created_at=timing.created_at if timing else utcnow(),
            entry_at=timing.entry_at if timing else None,
            entry_window_start=timing.entry_window_start if timing else None,
            entry_window_end=timing.entry_window_end if timing else None,
            expiry_at=timing.expiry_at if timing else None,
            reference_entry_price=None,
            features_snapshot=feature_data,
            decision_reason=result.reason,
        )
        self.db.add(signal)
        self.db.commit()
        self.db.refresh(signal)
        return signal
