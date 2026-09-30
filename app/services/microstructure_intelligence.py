from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings
from app.models.entities import SignalDirection
from app.services.market_data import MicrostructureDataCache, MicrostructureSnapshot, market_data_service
from app.signals.microstructure.decision import MicrostructureDecision, decide_microstructure
from app.signals.microstructure.features import MicrostructureFeatureSnapshot, build_microstructure_features
from app.signals.microstructure.scoring import score_microstructure_features

settings = get_settings()

ENGINE_NAME_V2 = 'BTC_MICROSTRUCTURE_V2'


@dataclass(frozen=True)
class MicrostructureIntelligenceResult:
    market: str
    direction: SignalDirection
    quality: str
    reference_price: float | None
    snapshot: MicrostructureSnapshot | None
    features: MicrostructureFeatureSnapshot | None
    decision: MicrostructureDecision | None
    reason: str
    service_available: bool = True
    engine: str = ENGINE_NAME_V2
    seconds_until_start: float | None = None
    contract_duration_seconds: float | None = None
    engine_details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            'market': self.market,
            'direction': self.direction.value,
            'quality': self.quality,
            'reference_price': self.reference_price,
            'reason': self.reason,
            'service_available': self.service_available,
            'engine': self.engine,
            'engine_details': self.engine_details,
        }


class MicrostructureIntelligenceService:
    """Experimental BTC 5-second microstructure prediction engine (BTC_MICROSTRUCTURE_V2).

    Runs completely in parallel to BTC_ORIGINAL_INTELLIGENCE_TIMER_V1.
    Never modifies production signals, Telegram broadcasts, or betting logic.
    """

    def __init__(self, cache: MicrostructureDataCache | None = None) -> None:
        self.cache = cache or MicrostructureDataCache()
        self._scan_lock = asyncio.Lock()
        self._last_result: MicrostructureIntelligenceResult | None = None
        self._last_result_at: float = 0.0
        self._last_compute_duration_ms: int | None = None
        self._compute_count = 0

    def operational_status(self) -> dict[str, Any]:
        age_ms = None
        if self._last_result is not None:
            age_ms = max(0, int((time.monotonic() - self._last_result_at) * 1000))
        return {
            'engine': ENGINE_NAME_V2,
            'has_completed_scan': self._last_result is not None,
            'last_scan_available': (
                self._last_result.service_available if self._last_result is not None else None
            ),
            'last_compute_duration_ms': self._last_compute_duration_ms,
            'last_result_age_ms': age_ms,
            'compute_count': self._compute_count,
        }

    async def scan(
        self,
        symbol: str | None = None,
        *,
        seconds_until_start: float | None = None,
        contract_duration_seconds: float | None = None,
        now: datetime | None = None,
    ) -> MicrostructureIntelligenceResult:
        market = (symbol or settings.analysis_pair).upper()
        if market != settings.analysis_pair.upper():
            return MicrostructureIntelligenceResult(
                market=market,
                direction=SignalDirection.NO_TRADE,
                quality='UNAVAILABLE',
                reference_price=None,
                snapshot=None,
                features=None,
                decision=None,
                reason=f'Unsupported market: {market}.',
                service_available=False,
                seconds_until_start=seconds_until_start,
                contract_duration_seconds=contract_duration_seconds,
            )

        async with self._scan_lock:
            started = time.monotonic()
            result = await self._compute(market, seconds_until_start, contract_duration_seconds, now=now)
            self._last_compute_duration_ms = max(0, int((time.monotonic() - started) * 1000))
            self._compute_count += 1
            self._last_result = result
            self._last_result_at = time.monotonic()
            return result

    async def _compute(
        self,
        market: str,
        seconds_until_start: float | None,
        contract_duration_seconds: float | None,
        now: datetime | None = None,
    ) -> MicrostructureIntelligenceResult:
        now_dt = now or datetime.now(timezone.utc)
        ms_snapshot = await self.cache.get_snapshot(
            market,
            max_book_age_seconds=settings.microstructure_book_max_age_seconds,
            max_depth_age_seconds=2.0,
            trade_lookback_seconds=10.0,
            reference_time=now_dt,
        )

        if ms_snapshot.book_ticker is None:
            return MicrostructureIntelligenceResult(
                market=market,
                direction=SignalDirection.NO_TRADE,
                quality='UNAVAILABLE',
                reference_price=None,
                snapshot=ms_snapshot,
                features=None,
                decision=None,
                reason='Live BTC book ticker stream has not warmed up yet.',
                service_available=False,
                seconds_until_start=seconds_until_start,
                contract_duration_seconds=contract_duration_seconds,
            )

        if not ms_snapshot.is_fresh:
            return MicrostructureIntelligenceResult(
                market=market,
                direction=SignalDirection.NO_TRADE,
                quality='UNAVAILABLE',
                reference_price=ms_snapshot.book_ticker.mid_price,
                snapshot=ms_snapshot,
                features=None,
                decision=None,
                reason='Live BTC microstructure stream is stale.',
                service_available=False,
                seconds_until_start=seconds_until_start,
                contract_duration_seconds=contract_duration_seconds,
            )

        candles = await market_data_service.get_cached_candles(market)

        book_history = await self.cache.get_book_history(market, lookback_seconds=10.0, reference_time=now_dt)

        try:
            features = build_microstructure_features(
                candles=candles,
                latest_book=ms_snapshot.book_ticker,
                book_history=book_history,
                depth=ms_snapshot.depth,
                depth_history=await self.cache.get_depth_history(market, lookback_seconds=10.0, reference_time=now_dt),
                recent_ticks=ms_snapshot.recent_ticks,
                now=now_dt,
                bars_5s=ms_snapshot.bars_5s,
                bar_metrics_5s=ms_snapshot.bar_metrics_5s,
            )
        except Exception as exc:
            return MicrostructureIntelligenceResult(
                market=market,
                direction=SignalDirection.NO_TRADE,
                quality='UNAVAILABLE',
                reference_price=ms_snapshot.book_ticker.mid_price,
                snapshot=ms_snapshot,
                features=None,
                decision=None,
                reason=f'BTC microstructure feature computation failed ({type(exc).__name__}).',
                service_available=False,
                seconds_until_start=seconds_until_start,
                contract_duration_seconds=contract_duration_seconds,
            )

        is_synth = bool(settings.detrade_use_synthetic_feed and features.bar_5s_range > 0)
        score = score_microstructure_features(features, is_synthetic=is_synth)
        decision = decide_microstructure(
            score=score,
            features=features,
            is_fresh=ms_snapshot.is_fresh,
            max_spread_bps=settings.microstructure_max_spread_bps,
            min_l5_volume=settings.microstructure_min_l5_volume,
            min_score=settings.microstructure_min_score,
            min_margin=settings.microstructure_min_margin,
            min_5s_range=settings.detrade_min_5s_range_dollars if is_synth else settings.signal_min_lead_range_dollars,
            max_5s_range=settings.detrade_max_5s_range_dollars if is_synth else 12.0,
            is_synthetic=is_synth,
            up_min_margin=getattr(settings, 'detrade_up_min_margin', 5) if is_synth else None,
            max_lead_impulse=getattr(settings, 'detrade_max_lead_impulse', 16.0),
        )

        details = {
            'engine': ENGINE_NAME_V2,
            'bull_score': decision.bull_score,
            'bear_score': decision.bear_score,
            'margin': decision.margin,
            'spread_bps': features.spread_bps,
            'obi_top': features.obi_top,
            'obi_l5': features.obi_l5,
            'microprice_dev_bps': features.microprice_dev_bps,
            'tfi_1s': features.tfi_1s,
            'velocity_1s_bps': features.velocity_1s_bps,
            'bar_5s_return': features.bar_5s_return,
            'bar_5s_range': features.bar_5s_range,
            'lead_range_dollars': features.lead_range_dollars,
            'bar_5s_taker_ratio': features.bar_5s_taker_ratio,
        }

        return MicrostructureIntelligenceResult(
            market=market,
            direction=decision.direction,
            quality=decision.quality,
            reference_price=ms_snapshot.book_ticker.mid_price,
            snapshot=ms_snapshot,
            features=features,
            decision=decision,
            reason=decision.reason,
            service_available=True,
            engine=ENGINE_NAME_V2,
            seconds_until_start=seconds_until_start,
            contract_duration_seconds=contract_duration_seconds,
            engine_details=details,
        )


microstructure_intelligence_service = MicrostructureIntelligenceService(
    cache=market_data_service.microstructure_cache
)

