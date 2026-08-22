from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, replace

from app.core.config import get_settings
from app.models.entities import SignalDirection
from app.services.market_data import MarketSnapshot, market_data_service
from app.signals.decision import SignalDecision, decide
from app.signals.features import FeatureSnapshot, build_features
from app.signals.scoring import score_features

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

        # Timing-aware scans must not reuse a cached decision produced for a
        # materially different prediction horizon.
        allow_cache = seconds_until_start is None and contract_duration_seconds is None
        max_cache_age = max(0.0, settings.signal_scan_coalesce_ms / 1000.0)
        now_mono = time.monotonic()
        if allow_cache and self._cached_result_is_usable(now_mono, max_cache_age):
            return self._last_result

        async with self._scan_lock:
            now_mono = time.monotonic()
            if allow_cache and self._cached_result_is_usable(now_mono, max_cache_age):
                return self._last_result
            result = await self._compute(
                market,
                seconds_until_start=seconds_until_start,
                contract_duration_seconds=contract_duration_seconds,
            )
            if allow_cache:
                self._last_result = result
                self._last_result_at = time.monotonic()
            return result

    def _cached_result_is_usable(self, now_mono: float, max_cache_age: float) -> bool:
        result = self._last_result
        if result is None or (now_mono - self._last_result_at) > max_cache_age:
            return False
        snapshot = result.market_snapshot
        if snapshot is None:
            return True
        age = time.time() - snapshot.event_time.timestamp()
        return -settings.market_data_future_skew_seconds <= age <= settings.market_data_max_age_seconds

    def _apply_horizon_gate(
        self,
        decision: SignalDecision,
        features: FeatureSnapshot,
        *,
        seconds_until_start: float | None,
        contract_duration_seconds: float | None,
    ) -> SignalDecision:
        if decision.direction == SignalDirection.NO_TRADE:
            return decision
        if seconds_until_start is None or contract_duration_seconds is None:
            return decision

        # This product is specifically the ~5 second Start Rate -> End Rate
        # contract. If the authoritative round says something materially
        # different, do not pretend the existing model targets that horizon.
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
            flow is not None and flow >= 0.60
            if direction_up
            else flow is not None and flow <= 0.40
        )
        aligned_momentum = (
            features.tick_return_1s_pct >= 0
            and features.tick_return_3s_pct >= 0.006
            and features.tick_return_5s_pct >= 0.01
            if direction_up
            else features.tick_return_1s_pct <= 0
            and features.tick_return_3s_pct <= -0.006
            and features.tick_return_5s_pct <= -0.01
        )
        aligned_context = (
            features.ema_fast > features.ema_slow and features.structure != 'BEARISH'
            if direction_up
            else features.ema_fast < features.ema_slow and features.structure != 'BULLISH'
        )

        # The farther away BCGAME's Start Rate is, the less predictive a current
        # one-second impulse is. Require progressively stronger persistence rather
        # than treating every scan as a five-second-from-now prediction.
        if seconds_until_start >= 10.0:
            required_score = 10
            required_margin = 6
            strong_flow = (
                flow is not None and flow >= 0.65
                if direction_up
                else flow is not None and flow <= 0.35
            )
            if (
                decision.bull_score < required_score if direction_up else decision.bear_score < required_score
            ) or decision.margin < required_margin or not strong_flow or not aligned_momentum or not aligned_context:
                return replace(
                    decision,
                    direction=SignalDirection.NO_TRADE,
                    quality='NO_TRADE',
                    reason='Setup is not persistent enough for the remaining time before BCGAME Start Rate.',
                )
        elif seconds_until_start >= 7.0:
            required_score = 9
            required_margin = 5
            directional_score = decision.bull_score if direction_up else decision.bear_score
            if directional_score < required_score or decision.margin < required_margin or not aligned_flow or not aligned_momentum:
                return replace(
                    decision,
                    direction=SignalDirection.NO_TRADE,
                    quality='NO_TRADE',
                    reason='Setup is not strong enough for this BCGAME prediction horizon.',
                )
        else:
            # Very late scans are handled by the timing service, but keep a final
            # intelligence guard here so the model never treats a late impulse as
            # a clean setup.
            if not aligned_flow or not aligned_momentum:
                return replace(
                    decision,
                    direction=SignalDirection.NO_TRADE,
                    quality='NO_TRADE',
                    reason='Late-round momentum is not sufficiently aligned.',
                )

        return decision

    async def _compute(
        self,
        market: str,
        *,
        seconds_until_start: float | None,
        contract_duration_seconds: float | None,
    ) -> IntelligenceResult:
        snapshot = await market_data_service.cache.get_snapshot(market, max_age_seconds=settings.market_data_max_age_seconds)
        if snapshot is None:
            return IntelligenceResult(market, SignalDirection.NO_TRADE, 'UNAVAILABLE', None, None, None, None, 'Live market data is temporarily unavailable.', False, seconds_until_start, contract_duration_seconds)
        if not snapshot.fresh:
            return IntelligenceResult(market, SignalDirection.NO_TRADE, 'UNAVAILABLE', snapshot.price, snapshot, None, None, 'Market data is stale. Try again shortly.', False, seconds_until_start, contract_duration_seconds)

        try:
            candles = await market_data_service.get_cached_candles(market)
            if not candles:
                raise RuntimeError('candle context cache is not ready')
            ticks = await market_data_service.cache.get_recent_ticks(
                market,
                lookback_seconds=settings.signal_trade_flow_lookback_seconds,
            )
            if len(ticks) < settings.signal_min_recent_trades:
                raise RuntimeError('insufficient recent trade data')
            tick_span = (max(t.event_time for t in ticks) - min(t.event_time for t in ticks)).total_seconds()
            if tick_span < settings.signal_min_tick_span_seconds:
                raise RuntimeError('recent trade window is too short')
            features = build_features(candles, ticks)
        except Exception as exc:
            return IntelligenceResult(
                market,
                SignalDirection.NO_TRADE,
                'UNAVAILABLE',
                snapshot.price,
                snapshot,
                None,
                None,
                f'Market analysis is temporarily unavailable ({type(exc).__name__}).',
                False,
                seconds_until_start,
                contract_duration_seconds,
            )

        score = score_features(features)
        min_score = max(8, settings.signal_min_score)
        min_margin = max(4, settings.signal_min_margin)
        decision = decide(score, min_score=min_score, min_margin=min_margin)
        decision = self._apply_horizon_gate(
            decision,
            features,
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
        )


signal_intelligence_service = SignalIntelligenceService()
