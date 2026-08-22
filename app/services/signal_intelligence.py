from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.models.entities import SignalDirection
from app.services.cross_venue_microstructure import cross_venue_microstructure_service
from app.services.market_data import MarketSnapshot, market_data_service
from app.signals.decision import SignalDecision
from app.signals.engine_v2 import btc_five_second_engine
from app.signals.features import FeatureSnapshot, build_features

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
    engine_details: dict[str, Any] | None = None


class SignalIntelligenceService:
    """Prepare fresh market inputs and run one unified directional engine.

    Availability checks live here. Prediction logic lives in engine_v2 and is
    evaluated once; there are intentionally no post-score veto layers.
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
        snapshot = await market_data_service.cache.get_snapshot(
            market,
            max_age_seconds=settings.market_data_max_age_seconds,
        )
        cross = cross_venue_microstructure_service.snapshot()
        cross_data = cross.to_dict() if settings.cross_venue_enabled else None

        if snapshot is None:
            return IntelligenceResult(
                market, SignalDirection.NO_TRADE, 'UNAVAILABLE', None, None, None, None,
                'Live BTC price stream has not warmed up yet.', False,
                seconds_until_start, contract_duration_seconds, cross_data,
            )
        if not snapshot.fresh:
            return IntelligenceResult(
                market, SignalDirection.NO_TRADE, 'UNAVAILABLE', snapshot.price, snapshot, None, None,
                'Live BTC price stream is stale.', False,
                seconds_until_start, contract_duration_seconds, cross_data,
            )

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

        outcome = btc_five_second_engine.evaluate(
            features,
            cross,
            seconds_until_start=seconds_until_start,
            contract_duration_seconds=contract_duration_seconds,
        )
        decision = outcome.decision

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
            engine_details=outcome.details,
        )


signal_intelligence_service = SignalIntelligenceService()
