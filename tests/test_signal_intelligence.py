from datetime import datetime, timedelta, timezone
from dataclasses import replace

from app.integrations.market_data.base import Candle, MarketTick
from app.models.entities import SignalDirection
from app.services.signal_intelligence import SignalIntelligenceService
from app.signals.decision import decide
from app.signals.features import build_features
from app.signals.scoring import ScoreResult, score_features


def make_candles(direction: int = 1) -> list[Candle]:
    now = datetime.now(timezone.utc) - timedelta(minutes=60)
    candles = []
    price = 60000.0
    for i in range(60):
        open_price = price
        close_price = price + (25.0 * direction)
        high = max(open_price, close_price) + 10
        low = min(open_price, close_price) - 10
        candles.append(Candle(
            symbol='BTCUSDT', interval='1m', open_time=now + timedelta(minutes=i),
            close_time=now + timedelta(minutes=i + 1), open=open_price, high=high, low=low,
            close=close_price, volume=100 + i, quote_volume=0, trade_count=100,
            taker_buy_base_volume=(70 + i) if direction > 0 else (30 + i / 4),
            taker_buy_quote_volume=0, closed=True, provider='TEST'))
        price = close_price
    return candles


def make_ticks(bullish: bool) -> list[MarketTick]:
    now = datetime.now(timezone.utc)
    return [MarketTick(
        symbol='BTCUSDT', price=61000 + (i if bullish else -i), quantity=1.0,
        event_time=now - timedelta(milliseconds=(19 - i) * 250),
        provider='TEST', is_buyer_maker=not bullish,
    ) for i in range(20)]


def test_bullish_features_can_produce_strong_up_signal():
    features = build_features(make_candles(1), make_ticks(True))
    score = score_features(features)
    result = decide(score)
    assert result.direction == SignalDirection.UP
    assert result.quality == 'STRONG'


def test_old_six_three_threshold_no_longer_qualifies_by_default():
    result = decide(ScoreResult(bull_score=7, bear_score=2, reasons=['legacy-strength setup']))
    assert result.direction == SignalDirection.NO_TRADE


def test_conflicting_scores_return_no_trade():
    result = decide(ScoreResult(bull_score=8, bear_score=5, reasons=['conflict']))
    assert result.direction == SignalDirection.NO_TRADE


def test_far_start_rate_requires_stronger_persistence():
    service = SignalIntelligenceService()
    features = build_features(make_candles(1), make_ticks(True))
    base = decide(ScoreResult(bull_score=9, bear_score=2, reasons=['strong but not long-horizon strong']), min_score=8, min_margin=4)
    gated = service._apply_horizon_gate(
        base,
        features,
        seconds_until_start=12.0,
        contract_duration_seconds=5.0,
    )
    assert gated.direction == SignalDirection.NO_TRADE
    assert 'Start Rate' in gated.reason


def test_wrong_contract_duration_is_rejected():
    service = SignalIntelligenceService()
    features = build_features(make_candles(1), make_ticks(True))
    base = decide(ScoreResult(bull_score=12, bear_score=1, reasons=['very strong']), min_score=8, min_margin=4)
    gated = service._apply_horizon_gate(
        base,
        features,
        seconds_until_start=10.0,
        contract_duration_seconds=7.0,
    )
    assert gated.direction == SignalDirection.NO_TRADE
    assert 'contract duration' in gated.reason
