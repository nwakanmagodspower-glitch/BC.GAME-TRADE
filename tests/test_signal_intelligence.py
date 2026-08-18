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


def make_ticks(bullish: bool) -> list[MarketTick]:
    now = datetime.now(timezone.utc)
    return [MarketTick(
        symbol='BTCUSDT', price=61000 + i, quantity=1.0, event_time=now,
        provider='TEST', is_buyer_maker=not bullish,
    ) for i in range(20)]


def test_bullish_features_can_produce_up_signal():
    features = build_features(make_candles(1), make_ticks(True))
    score = score_features(features)
    result = decide(score, min_score=6, min_margin=3)
    assert result.direction == SignalDirection.UP


def test_conflicting_scores_return_no_trade():
    from app.signals.scoring import ScoreResult
    result = decide(ScoreResult(bull_score=6, bear_score=5, reasons=['conflict']), min_score=6, min_margin=3)
    assert result.direction == SignalDirection.NO_TRADE
