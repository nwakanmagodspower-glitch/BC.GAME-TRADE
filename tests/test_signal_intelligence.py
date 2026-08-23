from datetime import datetime, timedelta, timezone

from app.integrations.market_data.base import Candle, MarketTick
from app.models.entities import SignalDirection
from app.signals.decision import decide
from app.signals.features import build_features
from app.signals.scoring import score_features


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


def make_ticks(bullish: bool, *, flat: bool = False) -> list[MarketTick]:
    now = datetime.now(timezone.utc)
    ticks = []
    for i in range(24):
        if flat:
            price = 61000.0 + (0.05 if i % 2 else -0.05)
            buyer_maker = bool(i % 2)
        else:
            price = 61000.0 + ((i * 1.2) if bullish else -(i * 1.2))
            buyer_maker = not bullish
        ticks.append(MarketTick(
            symbol='BTCUSDT', price=price, quantity=1.0,
            event_time=now - timedelta(milliseconds=(23 - i) * 250),
            provider='TEST', is_buyer_maker=buyer_maker,
        ))
    return ticks


def test_classic_engine_produces_up_when_momentum_and_flow_agree():
    features = build_features(make_candles(1), make_ticks(True))
    result = decide(score_features(features), min_score=6, min_margin=3)
    assert result.direction == SignalDirection.UP


def test_classic_engine_produces_down_when_momentum_and_flow_agree():
    features = build_features(make_candles(-1), make_ticks(False))
    result = decide(score_features(features), min_score=6, min_margin=3)
    assert result.direction == SignalDirection.DOWN


def test_flat_market_can_still_return_no_trade():
    features = build_features(make_candles(1), make_ticks(True, flat=True))
    result = decide(score_features(features), min_score=6, min_margin=3)
    assert result.direction == SignalDirection.NO_TRADE


def test_classic_policy_keeps_valid_and_strong_quality_levels():
    strong = decide(score_features(build_features(make_candles(1), make_ticks(True))), 6, 3)
    assert strong.quality in {'VALID', 'STRONG'}
