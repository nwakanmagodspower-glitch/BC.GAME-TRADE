from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, replace
from typing import Any

from app.core.config import get_settings
from app.models.entities import SignalDirection
from app.services.cross_venue_microstructure import CrossVenueSnapshot, cross_venue_microstructure_service
from app.services.market_data import MarketSnapshot, market_data_service
from app.signals.decision import SignalDecision, decide
from app.signals.features import FeatureSnapshot, build_features
from app.signals.scoring import ScoreResult, score_features

settings = get_settings()


@dataclass(frozen=True)
class IntelligenceResult:
    market: str
    direction: SignalDirection
    quality: str
    reference_price: float | None
    market_snapshot: MarketSnapshot | None
    features: FeatureSnapshot | None
    decision: SignalDecision | None
    reason: str
    service_available: bool = True
    seconds_until_start: float | None = None
    contract_duration_seconds: float | None = None
    cross_venue: dict[str, Any] | None = None


class SignalIntelligenceService:
    def __init__(self) -> None:
        self._scan_lock = asyncio.Lock()
        self._last_result: IntelligenceResult | None = None
        self._last_result_at: float = 0.0

    async def scan(
        self,
        symbol: str | None = None,
        *,
        seconds_until_start: float | None = None,
        contract_duration_seconds: float | None = None,
    ) -> IntelligenceResult:
        market = (symbol or settings.analysis_pair).upper()
        if market != settings.analysis_pair.upper():
            return IntelligenceResult(market, SignalDirection.NO_TRADE, 'UNAVAILABLE', None, None, None, None, f'Unsupported V1 market: {market}.', False, seconds_until_start, contract_duration_seconds)

        max_cache_age = max(0.0, settings.signal_scan_coalesce_ms / 1000.0)
        now_mono = time.monotonic()
        if self._cached_result_is_usable(
            now_mono,
            max_cache_age,
            seconds_until_start=seconds_until_start,
            contract_duration_seconds=contract_duration_seconds,
        ):
            assert self._last_result is not None
            return self._last_result

        async with self._scan_lock:
            now_mono = time.monotonic()
            if self._cached_result_is_usable(
                now_mono,
                max_cache_age,
                seconds_until_start=seconds_until_start,
                contract_duration_seconds=contract_duration_seconds,
            ):
                assert self._last_result is not None
                return self._last_result
            result = await self._compute(
                market,
                seconds_until_start=seconds_until_start,
                contract_duration_seconds=contract_duration_seconds,
            )
            self._last_result = result
            self._last_result_at = time.monotonic()
            return result

    def _cached_result_is_usable(
        self,
        now_mono: float,
        max_cache_age: float,
        *,
        seconds_until_start: float | None,
        contract_duration_seconds: float | None,
    ) -> bool:
        result = self._last_result
        if result is None or (now_mono - self._last_result_at) > max_cache_age:
            return False

        if seconds_until_start is None:
            if result.seconds_until_start is not None:
                return False
        else:
            if result.seconds_until_start is None or abs(result.seconds_until_start - seconds_until_start) > 0.5:
                return False

        if contract_duration_seconds is None:
            if result.contract_duration_seconds is not None:
                return False
        else:
            if result.contract_duration_seconds is None or abs(result.contract_duration_seconds - contract_duration_seconds) > 0.1:
                return False

        snapshot = result.market_snapshot
        if snapshot is None:
            return True
        age = time.time() - snapshot.event_time.timestamp()
        return -settings.market_data_future_skew_seconds <= age <= settings.market_data_max_age_seconds

    @staticmethod
    def _direction_matches_consensus(direction: SignalDirection, cross: CrossVenueSnapshot) -> bool:
        return (
            direction == SignalDirection.UP and cross.consensus == 'UP'
        ) or (
            direction == SignalDirection.DOWN and cross.consensus == 'DOWN'
        )

    @staticmethod
    def _apply_cross_venue_score_bonus(score: ScoreResult, cross: CrossVenueSnapshot) -> ScoreResult:
        """Treat genuine Binance+Bybit agreement as independent positive evidence.

        Earlier V1.4 builds used cross-venue data mostly as a veto after the base
        decision. That meant an otherwise useful 7-point setup could never become
        qualified even when both spot order books independently confirmed it.
        """
        if not settings.cross_venue_enabled or not cross.fresh or not cross.healthy_spread:
            return score
        reasons = list(score.reasons)
        if cross.consensus == 'UP':
            reasons.append('Binance and Bybit spot order books confirm UP')
            return ScoreResult(score.bull_score + 2, score.bear_score, reasons)
        if cross.consensus == 'DOWN':
            reasons.append('Binance and Bybit spot order books confirm DOWN')
            return ScoreResult(score.bull_score, score.bear_score + 2, reasons)
        return score

    def _apply_cross_venue_gate(
        self,
        decision: SignalDecision,
        cross: CrossVenueSnapshot,
    ) -> SignalDecision:
        if decision.direction == SignalDirection.NO_TRADE or not settings.cross_venue_enabled:
            return decision
        if not cross.fresh:
            return decision
        if not cross.healthy_spread:
            return replace(
                decision,
                direction=SignalDirection.NO_TRADE,
                quality='NO_TRADE',
                reason='Cross-venue spread/liquidity is abnormal for a five-second entry.',
            )
        if cross.consensus in {'UP', 'DOWN'} and not self._direction_matches_consensus(decision.direction, cross):
            return replace(
                decision,
                direction=SignalDirection.NO_TRADE,
                quality='NO_TRADE',
                reason='Binance and Bybit order books contradict the directional setup.',
            )
        return decision

    def _apply_horizon_gate(
        self,
        decision: SignalDecision,
        features: FeatureSnapshot,
        cross: CrossVenueSnapshot,
        *,
        seconds_until_start: float | None,
        contract_duration_seconds: float | None,
    ) -> SignalDecision:
        if decision.direction == SignalDirection.NO_TRADE:
            return decision
        if seconds_until_start is None or contract_duration_seconds is None:
            return decision

        if not 4.5 <= contract_duration_seconds <= 5.5:
            return replace(
                decision,
                direction=SignalDirection.NO_TRADE,
                quality='NO_TRADE',
                reason='Authoritative BCGAME contract duration does not match the 5-second strategy horizon.',
            )

        direction_up = decision.direction == SignalDirection.UP
        flow = features.trade_buy_ratio
        aligned_flow = (
            flow is not None and flow >= 0.56
            if direction_up
            else flow is not None and flow <= 0.44
        )
        # Persistence matters more than requiring every window to be positive by
        # the exact same threshold. A tiny opposite 1s print is tolerated unless
        # it reaches the explicit reversal veto already applied in scoring.
        aligned_momentum = (
            features.tick_return_1s_pct >= -0.0015
            and features.tick_return_3s_pct >= 0.004
            and features.tick_return_5s_pct >= 0.007
            if direction_up
            else features.tick_return_1s_pct <= 0.0015
            and features.tick_return_3s_pct <= -0.004
            and features.tick_return_5s_pct <= -0.007
        )
        cross_confirmed = cross.fresh and cross.healthy_spread and self._direction_matches_consensus(decision.direction, cross)
        directional_score = decision.bull_score if direction_up else decision.bear_score

        # Long prediction horizons remain somewhat stricter, but cross-venue
        # confirmation must not be counted twice. When both spot venues agree,
        # the normal 8/4 decision plus persistent micro-momentum is sufficient.
        if seconds_until_start >= 10.0:
            if cross_confirmed:
                if directional_score < 8 or decision.margin < 4 or not aligned_momentum:
                    return replace(
                        decision,
                        direction=SignalDirection.NO_TRADE,
                        quality='NO_TRADE',
                        reason='Cross-venue direction is aligned, but momentum is not persistent enough for the time remaining before BCGAME Start Rate.',
                    )
            else:
                if directional_score < 9 or decision.margin < 5 or not aligned_flow or not aligned_momentum:
                    return replace(
                        decision,
                        direction=SignalDirection.NO_TRADE,
                        quality='NO_TRADE',
                        reason='Setup is not persistent enough for the remaining time before BCGAME Start Rate.',
                    )
        elif seconds_until_start >= 7.0:
            if cross_confirmed:
                if directional_score < 8 or decision.margin < 4 or not aligned_momentum:
                    return replace(
                        decision,
                        direction=SignalDirection.NO_TRADE,
                        quality='NO_TRADE',
                        reason='Cross-venue direction is aligned, but short-term momentum is not strong enough for this BCGAME horizon.',
                    )
            elif not aligned_flow or not aligned_momentum:
                return replace(
                    decision,
                    direction=SignalDirection.NO_TRADE,
                    quality='NO_TRADE',
                    reason='Setup needs either cross-venue confirmation or aligned Binance flow for this BCGAME horizon.',
                )
        else:
            if cross_confirmed:
                if not aligned_momentum:
                    return replace(
                        decision,
                        direction=SignalDirection.NO_TRADE,
                        quality='NO_TRADE',
                        reason='Cross-venue direction is aligned, but late-round momentum is reversing.',
                    )
            elif not aligned_flow or not aligned_momentum:
                return replace(
                    decision,
                    direction=SignalDirection.NO_TRADE,
                    quality='NO_TRADE',
                    reason='Late-round momentum/flow is not sufficiently aligned.',
                )

        if cross_confirmed:
            return replace(decision, quality='STRONG')
        return decision

    async def _compute(
        self,
        market: str,
        *,
        seconds_until_start: float | None,
        contract_duration_seconds: float | None,
    ) -> IntelligenceResult:
        snapshot = await market_data_service.cache.get_snapshot(market, max_age_seconds=settings.market_data_max_age_seconds)
        cross = cross_venue_microstructure_service.snapshot()
        cross_data = cross.to_dict() if settings.cross_venue_enabled else None
        if snapshot is None:
            return IntelligenceResult(market, SignalDirection.NO_TRADE, 'UNAVAILABLE', None, None, None, None, 'Live BTC price stream has not warmed up yet.', False, seconds_until_start, contract_duration_seconds, cross_data)
        if not snapshot.fresh:
            return IntelligenceResult(market, SignalDirection.NO_TRADE, 'UNAVAILABLE', snapshot.price, snapshot, None, None, 'Live BTC price stream is stale.', False, seconds_until_start, contract_duration_seconds, cross_data)

        candles = await market_data_service.get_cached_candles(market)
        if not candles:
            return IntelligenceResult(
                market, SignalDirection.NO_TRADE, 'UNAVAILABLE', snapshot.price, snapshot, None, None,
                'BTC candle context is refreshing.', False,
                seconds_until_start, contract_duration_seconds, cross_data,
            )

        ticks = await market_data_service.cache.get_recent_ticks(
            market,
            lookback_seconds=settings.signal_trade_flow_lookback_seconds,
        )
        if len(ticks) < settings.signal_min_recent_trades:
            return IntelligenceResult(
                market, SignalDirection.NO_TRADE, 'UNAVAILABLE', snapshot.price, snapshot, None, None,
                'BTC trade stream is warming up.', False,
                seconds_until_start, contract_duration_seconds, cross_data,
            )
        tick_span = (max(t.event_time for t in ticks) - min(t.event_time for t in ticks)).total_seconds()
        if tick_span < settings.signal_min_tick_span_seconds:
            return IntelligenceResult(
                market, SignalDirection.NO_TRADE, 'UNAVAILABLE', snapshot.price, snapshot, None, None,
                'BTC trade-history window is rebuilding.', False,
                seconds_until_start, contract_duration_seconds, cross_data,
            )

        try:
            features = build_features(candles, ticks)
        except Exception as exc:
            return IntelligenceResult(
                market, SignalDirection.NO_TRADE, 'UNAVAILABLE', snapshot.price, snapshot, None, None,
                f'BTC feature preparation failed ({type(exc).__name__}).', False,
                seconds_until_start, contract_duration_seconds, cross_data,
            )

        score = score_features(features)
        score = self._apply_cross_venue_score_bonus(score, cross)
        decision = decide(score, min_score=max(8, settings.signal_min_score), min_margin=max(4, settings.signal_min_margin))
        decision = self._apply_cross_venue_gate(decision, cross)
        decision = self._apply_horizon_gate(
            decision,
            features,
            cross,
            seconds_until_start=seconds_until_start,
            contract_duration_seconds=contract_duration_seconds,
        )

        return IntelligenceResult(
            market=market,
            direction=decision.direction,
            quality=decision.quality,
            reference_price=snapshot.price,
            market_snapshot=snapshot,
            features=features,
            decision=decision,
            reason=decision.reason,
            service_available=True,
            seconds_until_start=seconds_until_start,
            contract_duration_seconds=contract_duration_seconds,
            cross_venue=cross_data,
        )


signal_intelligence_service = SignalIntelligenceService()
