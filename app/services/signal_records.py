from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.bcgame_rounds import BCGameRoundSnapshot
from app.models.entities import BCGameRound, Signal, SignalDirection, SignalStatus, utcnow
from app.services.signal_intelligence import IntelligenceResult

settings = get_settings()


class SignalRecordService:
    def __init__(self, db: Session):
        self.db = db

    def _persist_round(self, snapshot: BCGameRoundSnapshot) -> BCGameRound:
        row = self.db.scalar(select(BCGameRound).where(BCGameRound.external_round_id == snapshot.round_id))
        if row is None:
            row = BCGameRound(
                external_round_id=snapshot.round_id,
                game_market=settings.game_market,
                duration_seconds=settings.default_expiry_seconds,
                stake_band=snapshot.stake_band,
                observed_at=snapshot.observed_at,
                order_closes_at=snapshot.order_closes_at,
                start_rate_at=snapshot.start_rate_at,
                end_rate_at=snapshot.end_rate_at,
                up_payout_pct=snapshot.up_payout_pct,
                down_payout_pct=snapshot.down_payout_pct,
                up_pool_amount=snapshot.up_pool_amount,
                down_pool_amount=snapshot.down_pool_amount,
                up_players=snapshot.up_players,
                down_players=snapshot.down_players,
                source=snapshot.source,
            )
            self.db.add(row); self.db.flush()
        return row

    def record_scan(self, result: IntelligenceResult, requested_by_user_id: int | None = None, round_snapshot: BCGameRoundSnapshot | None = None) -> Signal:
        if not result.service_available:
            raise ValueError('Unavailable market/service states cannot be persisted as strategy signals.')
        if result.market.upper() != settings.analysis_pair.upper():
            raise ValueError('Unsupported V1 analysis market cannot be persisted.')

        is_trade = result.direction in {SignalDirection.UP, SignalDirection.DOWN}
        if is_trade and round_snapshot is None:
            raise ValueError('Directional five-second signals require a timing snapshot.')

        round_row = self._persist_round(round_snapshot) if round_snapshot is not None else None
        status = SignalStatus.WAITING_ENTRY if is_trade else SignalStatus.NO_TRADE
        feature_data = result.features.to_dict() if result.features is not None else {}
        if result.decision is not None:
            feature_data['_decision'] = {'quality': result.quality, 'bull_score': result.decision.bull_score, 'bear_score': result.decision.bear_score}
        feature_data['_market'] = {
            'game_market': settings.game_market,
            'analysis_pair': result.market,
            'scan_price': result.reference_price,
            'provider': result.market_snapshot.provider if result.market_snapshot else None,
            'event_time': result.market_snapshot.event_time.isoformat() if result.market_snapshot else None,
            'external_reference_only': True,
        }
        if round_snapshot is not None:
            feature_data['_bcgame_round'] = {
                'round_id': round_snapshot.round_id,
                'source': round_snapshot.source,
                'order_closes_at': round_snapshot.order_closes_at.isoformat(),
                'start_rate_at': round_snapshot.start_rate_at.isoformat(),
                'end_rate_at': round_snapshot.end_rate_at.isoformat(),
                'stake_band': round_snapshot.stake_band,
                'up_payout_pct': round_snapshot.up_payout_pct,
                'down_payout_pct': round_snapshot.down_payout_pct,
                'up_pool_amount': round_snapshot.up_pool_amount,
                'down_pool_amount': round_snapshot.down_pool_amount,
                'up_players': round_snapshot.up_players,
                'down_players': round_snapshot.down_players,
            }

        signal = Signal(
            requested_by_user_id=requested_by_user_id,
            bcgame_round_id=round_row.id if round_row else None,
            market=settings.game_market,
            product=settings.default_product,
            direction=result.direction,
            status=status,
            strategy_version=settings.strategy_version,
            confidence=None,
            created_at=utcnow(),
            entry_at=round_snapshot.start_rate_at if round_snapshot else None,
            entry_window_start=None,
            entry_window_end=round_snapshot.order_closes_at if round_snapshot else None,
            expiry_at=round_snapshot.end_rate_at if round_snapshot else None,
            reference_entry_price=None,
            features_snapshot=feature_data,
            decision_reason=result.reason,
        )
        self.db.add(signal); self.db.commit(); self.db.refresh(signal)
        return signal
