from datetime import datetime, timedelta, timezone

from app.integrations.market_data.base import Candle, MarketTick
from app.models.entities import SignalDirection
from app.services.signal_intelligence import (
    ENGINE_NAME,
    IntelligenceResult,
    SignalIntelligenceService,
)
from app.signals.decision import decide
from app.signals.features import build_features
from app.signals.scoring import score_features


def make_candles(direction: int = 1) -> list[Candle]:
    now = datetime.now(timezone.utc) - timedelta(minutes=60)
    candles = []
    price = 60000.0
    for i in range(60):
        open_price = price
        step = 25.0 * direction if direction else (2.0 if i % 2 else -2.0)
        close_price = price + step
        high = max(open_price, close_price) + 10
        low = min(open_price, close_price) - 10
        candles.append(Candle(
            symbol='BTCUSDT', interval='1m', open_time=now + timedelta(minutes=i),
            close_time=now + timedelta(minutes=i + 1), open=open_price, high=high, low=low,
            close=close_price, volume=100 + i, quote_volume=0, trade_count=100,
            taker_buy_base_volume=(70 + i) if direction > 0 else ((30 + i / 4) if direction < 0 else 50),
            taker_buy_quote_volume=0, closed=True, provider='TEST'))
        price = close_price
    return candles


def make_ticks(bullish: bool, *, balanced: bool = False) -> list[MarketTick]:
    now = datetime.now(timezone.utc)
    ticks = []
    for i in range(24):
        buyer_maker = bool(i % 2) if balanced else not bullish
        ticks.append(MarketTick(
            symbol='BTCUSDT', price=61000.0, quantity=1.0,
            event_time=now - timedelta(milliseconds=(23 - i) * 250),
            provider='TEST', is_buyer_maker=buyer_maker,
        ))
    return ticks


def test_original_engine_produces_up_when_context_and_flow_agree():
    features = build_features(make_candles(1), make_ticks(True))
    result = decide(score_features(features), min_score=6, min_margin=3)
    assert result.direction == SignalDirection.UP


def test_original_engine_produces_down_when_context_and_flow_agree():
    features = build_features(make_candles(-1), make_ticks(False))
    result = decide(score_features(features), min_score=6, min_margin=3)
    assert result.direction == SignalDirection.DOWN


def test_neutral_context_and_balanced_flow_return_no_trade():
    features = build_features(make_candles(0), make_ticks(True, balanced=True))
    result = decide(score_features(features), min_score=6, min_margin=3)
    assert result.direction == SignalDirection.NO_TRADE


def test_original_policy_keeps_valid_and_strong_quality_levels():
    strong = decide(score_features(build_features(make_candles(1), make_ticks(True))), 6, 3)
    assert strong.quality in {'VALID', 'STRONG'}


def test_timer_metadata_cannot_change_prediction_direction_or_score():
    decision = decide(score_features(build_features(make_candles(1), make_ticks(True))), 6, 3)
    base = IntelligenceResult(
        market='BTCUSDT',
        direction=decision.direction,
        quality=decision.quality,
        reference_price=61000.0,
        market_snapshot=None,
        features=None,
        decision=decision,
        reason=decision.reason,
        engine_details={
            'engine': ENGINE_NAME,
            'bull_score': decision.bull_score,
            'bear_score': decision.bear_score,
            'margin': decision.margin,
        },
    )

    early = SignalIntelligenceService._with_timer(base, 12.0, 5.0)
    late = SignalIntelligenceService._with_timer(base, 3.0, 5.0)
    wrong_duration = SignalIntelligenceService._with_timer(base, 12.0, 7.0)

    for timed in (early, late, wrong_duration):
        assert timed.direction == base.direction
        assert timed.decision == base.decision
        assert timed.engine_details['bull_score'] == decision.bull_score
        assert timed.engine_details['bear_score'] == decision.bear_score
        assert timed.engine_details['margin'] == decision.margin

    assert early.engine_details['timer_validated'] is True
    assert late.engine_details['timer_validated'] is True
    assert wrong_duration.engine_details['timer_validated'] is False
