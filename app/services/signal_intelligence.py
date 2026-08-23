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

ENGINE_NAME = 'BTC_ORIGINAL_INTELLIGENCE_TIMER_V1'


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
    engine_details: dict[str, Any] | None = None


class SignalIntelligenceService:
    """Original BTC intelligence with BC.Game timing kept outside prediction.

    The prediction core is the first pre-timer engine: EMA trend, five-minute
    momentum, short-term structure, volume/taker behavior, recent aggressive
    trade flow, RSI and ATR. The DeTrade/BC.Game timer may validate the product
    and tell the delivery layer when a round can be used, but it never adds
    directional weights, horizon penalties, external venue votes or extra vetoes.
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
                market=market,
                direction=SignalDirection.NO_TRADE,
                quality='UNAVAILABLE',
                reference_price=None,
                market_snapshot=None,
                features=None,
                decision=None,
                reason=f'Unsupported market: {market}.',
                service_available=False,
                seconds_until_start=seconds_until_start,
                contract_duration_seconds=contract_duration_seconds,
            )

        max_cache_age = max(0.0, settings.signal_scan_coalesce_ms / 1000.0)
        now_mono = time.monotonic()
        if self._cached_result_is_usable(now_mono, max_cache_age):
            assert self._last_result is not None
            return self._with_timer(self._last_result, seconds_until_start, contract_duration_seconds)

        async with self._scan_lock:
            now_mono = time.monotonic()
            if self._cached_result_is_usable(now_mono, max_cache_age):
                assert self._last_result is not None
                return self._with_timer(self._last_result, seconds_until_start, contract_duration_seconds)

            result = await self._compute(market)
            self._last_result = result
            self._last_result_at = time.monotonic()
            return self._with_timer(result, seconds_until_start, contract_duration_seconds)

    def _cached_result_is_usable(self, now_mono: float, max_cache_age: float) -> bool:
        result = self._last_result
        if result is None or (now_mono - self._last_result_at) > max_cache_age:
            return False
        snapshot = result.market_snapshot
        if snapshot is None:
            return True
        age = time.time() - snapshot.event_time.timestamp()
        return -settings.market_data_future_skew_seconds <= age <= settings.market_data_max_age_seconds

    @staticmethod
    def _with_timer(
        result: IntelligenceResult,
        seconds_until_start: float | None,
        contract_duration_seconds: float | None,
    ) -> IntelligenceResult:
        timer_validated = (
            contract_duration_seconds is None
            or 4.5 <= contract_duration_seconds <= 5.5
        )
        details = dict(result.engine_details or {})
        details.update(
            {
                'timer_validated': timer_validated,
                'seconds_until_start': seconds_until_start,
                'contract_duration_seconds': contract_duration_seconds,
            }
        )
        return IntelligenceResult(
            market=result.market,
            direction=result.direction,
            quality=result.quality,
            reference_price=result.reference_price,
            market_snapshot=result.market_snapshot,
            features=result.features,
            decision=result.decision,
            reason=result.reason,
            service_available=result.service_available,
            seconds_until_start=seconds_until_start,
            contract_duration_seconds=contract_duration_seconds,
            engine_details=details,
        )

    async def _compute(self, market: str) -> IntelligenceResult:
        snapshot = await market_data_service.cache.get_snapshot(
            market,
            max_age_seconds=settings.market_data_max_age_seconds,
        )
        if snapshot is None:
            return IntelligenceResult(
                market, SignalDirection.NO_TRADE, 'UNAVAILABLE', None, None, None, None,
                'Live BTC price stream has not warmed up yet.', False,
            )
        if not snapshot.fresh:
            return IntelligenceResult(
                market, SignalDirection.NO_TRADE, 'UNAVAILABLE', snapshot.price, snapshot, None, None,
                'Live BTC price stream is stale.', False,
            )

        candles = await market_data_service.get_cached_candles(market)
        if not candles:
            return IntelligenceResult(
                market, SignalDirection.NO_TRADE, 'UNAVAILABLE', snapshot.price, snapshot, None, None,
                'BTC candle context is refreshing.', False,
            )

        ticks = await market_data_service.cache.get_recent_ticks(
            market,
            lookback_seconds=settings.signal_trade_flow_lookback_seconds,
        )

        try:
            features = build_features(candles, ticks)
        except Exception as exc:
            return IntelligenceResult(
                market, SignalDirection.NO_TRADE, 'UNAVAILABLE', snapshot.price, snapshot, None, None,
                f'BTC feature preparation failed ({type(exc).__name__}).', False,
            )

        score = score_features(features)
        decision = decide(
            score,
            min_score=settings.signal_min_score,
            min_margin=settings.signal_min_margin,
        )
        details = {
            'engine': ENGINE_NAME,
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
            engine_details=details,
        )


signal_intelligence_service = SignalIntelligenceService()
