from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

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


class SignalIntelligenceService:
    def __init__(self) -> None:
        self._scan_lock = asyncio.Lock()
        self._last_result: IntelligenceResult | None = None
        self._last_result_at: float = 0.0

    async def scan(self, symbol: str | None = None) -> IntelligenceResult:
        market = (symbol or settings.analysis_pair).upper()
        if market != settings.analysis_pair.upper():
            return IntelligenceResult(market, SignalDirection.NO_TRADE, 'UNAVAILABLE', None, None, None, None, f'Unsupported V1 market: {market}.', False)

        max_cache_age = max(0.0, settings.signal_scan_coalesce_ms / 1000.0)
        now_mono = time.monotonic()
        if self._last_result is not None and (now_mono - self._last_result_at) <= max_cache_age:
            return self._last_result

        async with self._scan_lock:
            now_mono = time.monotonic()
            if self._last_result is not None and (now_mono - self._last_result_at) <= max_cache_age:
                return self._last_result
            result = await self._compute(market)
            self._last_result = result
            self._last_result_at = time.monotonic()
            return result

    async def _compute(self, market: str) -> IntelligenceResult:
        snapshot = await market_data_service.cache.get_snapshot(market, max_age_seconds=settings.market_data_max_age_seconds)
        if snapshot is None:
            return IntelligenceResult(market, SignalDirection.NO_TRADE, 'UNAVAILABLE', None, None, None, None, 'Live market data is temporarily unavailable.', False)
        if not snapshot.fresh:
            return IntelligenceResult(market, SignalDirection.NO_TRADE, 'UNAVAILABLE', snapshot.price, snapshot, None, None, 'Market data is stale. Try again shortly.', False)

        try:
            # Slow 1m context is refreshed in the background. The time-sensitive
            # scan path performs no REST candle download.
            candles = await market_data_service.get_cached_candles(market)
            if not candles:
                raise RuntimeError('candle context cache is not ready')
            ticks = await market_data_service.cache.get_recent_ticks(market, lookback_seconds=settings.signal_trade_flow_lookback_seconds)
            features = build_features(candles, ticks)
        except Exception as exc:
            return IntelligenceResult(market, SignalDirection.NO_TRADE, 'UNAVAILABLE', snapshot.price, snapshot, None, None, f'Market analysis is temporarily unavailable ({type(exc).__name__}).', False)

        score = score_features(features)
        decision = decide(score, min_score=settings.signal_min_score, min_margin=settings.signal_min_margin)
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
        )


signal_intelligence_service = SignalIntelligenceService()
