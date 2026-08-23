from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.models.entities import SignalDirection
from app.services.market_data import MarketSnapshot, market_data_service
from app.signals.decision import SignalDecision, decide
from app.signals.features import FeatureSnapshot, build_features
from app.signals.scoring import score_features

settings = get_settings()

ENGINE_NAME = 'BTC_5S_CLASSIC_TIMER_V1'


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
    engine_details: dict[str, Any] | None = None


class SignalIntelligenceService:
    """Classic BTC five-second intelligence with timing kept separate.

    Direction comes only from the original momentum/flow/context scorer. DeTrade
    timing validates that the BCGAME contract is the expected five-second product;
    it never adds directional weights, horizon penalties, or extra veto stacks.
    """

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
            return IntelligenceResult(
                market, SignalDirection.NO_TRADE, 'UNAVAILABLE', None, None, None, None,
                f'Unsupported market: {market}.', False,
                seconds_until_start, contract_duration_seconds,
            )

        max_cache_age = max(0.0, settings.signal_scan_coalesce_ms / 1000.0)
        now_mono = time.monotonic()
        if self._cached_result_is_usable(now_mono, max_cache_age, seconds_until_start, contract_duration_seconds):
            assert self._last_result is not None
            return self._last_result

        async with self._scan_lock:
            now_mono = time.monotonic()
            if self._cached_result_is_usable(now_mono, max_cache_age, seconds_until_start, contract_duration_seconds):
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
        seconds_until_start: float | None,
        contract_duration_seconds: float | None,
    ) -> bool:
        result = self._last_result
        if result is None or (now_mono - self._last_result_at) > max_cache_age:
            return False
        if seconds_until_start is None:
            if result.seconds_until_start is not None:
                return False
        elif result.seconds_until_start is None or abs(result.seconds_until_start - seconds_until_start) > 0.5:
            return False
        if contract_duration_seconds is None:
            if result.contract_duration_seconds is not None:
                return False
        elif result.contract_duration_seconds is None or abs(result.contract_duration_seconds - contract_duration_seconds) > 0.1:
            return False
        snapshot = result.market_snapshot
        if snapshot is None:
            return True
        age = time.time() - snapshot.event_time.timestamp()
        return -settings.market_data_future_skew_seconds <= age <= settings.market_data_max_age_seconds

    async def _compute(
        self,
        market: str,
        *,
        seconds_until_start: float | None,
        contract_duration_seconds: float | None,
    ) -> IntelligenceResult:
        # Timing is a product/window validator only. It never changes direction.
        if contract_duration_seconds is not None and not 4.5 <= contract_duration_seconds <= 5.5:
            decision = SignalDecision(
                direction=SignalDirection.NO_TRADE,
                quality='NO_TRADE',
                bull_score=0,
                bear_score=0,
                margin=0,
                reason='BCGAME round duration does not match the five-second strategy.',
            )
            return IntelligenceResult(
                market, decision.direction, decision.quality, None, None, None, decision,
                decision.reason, True, seconds_until_start, contract_duration_seconds,
                None, {'engine': ENGINE_NAME, 'timer_validated': False},
            )

        snapshot = await market_data_service.cache.get_snapshot(
            market,
            max_age_seconds=settings.market_data_max_age_seconds,
        )
        if snapshot is None:
            return IntelligenceResult(
                market, SignalDirection.NO_TRADE, 'UNAVAILABLE', None, None, None, None,
                'Live BTC price stream has not warmed up yet.', False,
                seconds_until_start, contract_duration_seconds,
            )
        if not snapshot.fresh:
            return IntelligenceResult(
                market, SignalDirection.NO_TRADE, 'UNAVAILABLE', snapshot.price, snapshot, None, None,
                'Live BTC price stream is stale.', False,
                seconds_until_start, contract_duration_seconds,
            )

        candles = await market_data_service.get_cached_candles(market)
        if not candles:
            return IntelligenceResult(
                market, SignalDirection.NO_TRADE, 'UNAVAILABLE', snapshot.price, snapshot, None, None,
                'BTC candle context is refreshing.', False,
                seconds_until_start, contract_duration_seconds,
            )

        ticks = await market_data_service.cache.get_recent_ticks(
            market,
            lookback_seconds=settings.signal_trade_flow_lookback_seconds,
        )
        if len(ticks) < settings.signal_min_recent_trades:
            return IntelligenceResult(
                market, SignalDirection.NO_TRADE, 'UNAVAILABLE', snapshot.price, snapshot, None, None,
                'BTC trade stream is warming up.', False,
                seconds_until_start, contract_duration_seconds,
            )

        tick_span = (max(t.event_time for t in ticks) - min(t.event_time for t in ticks)).total_seconds()
        if tick_span < settings.signal_min_tick_span_seconds:
            return IntelligenceResult(
                market, SignalDirection.NO_TRADE, 'UNAVAILABLE', snapshot.price, snapshot, None, None,
                'BTC trade-history window is rebuilding.', False,
                seconds_until_start, contract_duration_seconds,
            )

        try:
            features = build_features(candles, ticks)
        except Exception as exc:
            return IntelligenceResult(
                market, SignalDirection.NO_TRADE, 'UNAVAILABLE', snapshot.price, snapshot, None, None,
                f'BTC feature preparation failed ({type(exc).__name__}).', False,
                seconds_until_start, contract_duration_seconds,
            )

        # Intentionally fixed to the original 6/3 policy so old Render 8/4 env
        # values cannot silently turn this reset back into the over-strict engine.
        score = score_features(features)
        decision = decide(score, min_score=6, min_margin=3)
        details = {
            'engine': ENGINE_NAME,
            'timer_validated': contract_duration_seconds is None or 4.5 <= contract_duration_seconds <= 5.5,
            'seconds_until_start': seconds_until_start,
            'contract_duration_seconds': contract_duration_seconds,
            'bull_score': decision.bull_score,
            'bear_score': decision.bear_score,
            'margin': decision.margin,
        }

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
            cross_venue=None,
            engine_details=details,
        )


signal_intelligence_service = SignalIntelligenceService()
