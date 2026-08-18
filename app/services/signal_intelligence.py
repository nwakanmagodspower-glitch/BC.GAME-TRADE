from __future__ import annotations

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
    async def scan(self, symbol: str | None = None) -> IntelligenceResult:
        market = (symbol or settings.default_pair).upper()
        if market != settings.default_pair.upper():
            return IntelligenceResult(
                market=market,
                direction=SignalDirection.NO_TRADE,
                quality='UNAVAILABLE',
                reference_price=None,
                market_snapshot=None,
                features=None,
                decision=None,
                reason=f'Unsupported V1 market: {market}.',
                service_available=False,
            )

        snapshot = await market_data_service.cache.get_snapshot(market, max_age_seconds=settings.market_data_max_age_seconds)
        if snapshot is None:
            return IntelligenceResult(
                market=market,
                direction=SignalDirection.NO_TRADE,
                quality='UNAVAILABLE',
                reference_price=None,
                market_snapshot=None,
                features=None,
                decision=None,
                reason='Live market data is temporarily unavailable.',
                service_available=False,
            )
        if not snapshot.fresh:
            return IntelligenceResult(
                market=market,
                direction=SignalDirection.NO_TRADE,
                quality='UNAVAILABLE',
                reference_price=snapshot.price,
                market_snapshot=snapshot,
                features=None,
                decision=None,
                reason='Market data is stale. Try again shortly.',
                service_available=False,
            )

        try:
            candles = await market_data_service.fetch_candles(market, '1m', limit=max(100, settings.market_data_kline_limit))
            ticks = await market_data_service.cache.get_recent_ticks(market, lookback_seconds=settings.signal_trade_flow_lookback_seconds)
            features = build_features(candles, ticks)
        except Exception as exc:
            return IntelligenceResult(
                market=market,
                direction=SignalDirection.NO_TRADE,
                quality='UNAVAILABLE',
                reference_price=snapshot.price,
                market_snapshot=snapshot,
                features=None,
                decision=None,
                reason=f'Market analysis is temporarily unavailable ({type(exc).__name__}).',
                service_available=False,
            )

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
