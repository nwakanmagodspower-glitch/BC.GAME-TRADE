from datetime import datetime, timedelta, timezone

from app.integrations.market_data.base import Candle, MarketTick
from app.models.entities import SignalDirection
from app.services.cross_venue_microstructure import CrossVenueSnapshot, VenueBookSnapshot
from app.signals.engine_v2 import BTCFiveSecondEngine
from app.signals.features import build_features


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


def cross(direction: str) -> CrossVenueSnapshot:
    now = datetime.now(timezone.utc)
    if direction == 'UP':
        return CrossVenueSnapshot(
            binance=VenueBookSnapshot('BINANCE', 100.0, 100.1, 9.0, 1.0, 70.0, 30.0, now),
            bybit=VenueBookSnapshot('BYBIT', 100.0, 100.1, 8.0, 2.0, 68.0, 32.0, now),
        )
    if direction == 'DOWN':
        return CrossVenueSnapshot(
            binance=VenueBookSnapshot('BINANCE', 100.0, 100.1, 1.0, 9.0, 30.0, 70.0, now),
            bybit=VenueBookSnapshot('BYBIT', 100.0, 100.1, 2.0, 8.0, 32.0, 68.0, now),
        )
    return CrossVenueSnapshot(binance=None, bybit=None)


def test_unified_engine_produces_up_when_live_evidence_agrees():
    features = build_features(make_candles(1), make_ticks(True))
    result = BTCFiveSecondEngine().evaluate(
        features,
        cross('UP'),
        seconds_until_start=11.0,
        contract_duration_seconds=5.0,
    )
    assert result.decision.direction == SignalDirection.UP
    assert result.details['edge'] > result.details['threshold']


def test_unified_engine_produces_down_when_live_evidence_agrees():
    features = build_features(make_candles(-1), make_ticks(False))
    result = BTCFiveSecondEngine().evaluate(
        features,
        cross('DOWN'),
        seconds_until_start=8.0,
        contract_duration_seconds=5.0,
    )
    assert result.decision.direction == SignalDirection.DOWN
    assert abs(result.details['edge']) > result.details['threshold']


def test_far_horizon_changes_weighting_but_does_not_add_second_veto():
    features = build_features(make_candles(1), make_ticks(True))
    engine = BTCFiveSecondEngine()
    near = engine.evaluate(features, cross('UP'), seconds_until_start=5.0, contract_duration_seconds=5.0)
    far = engine.evaluate(features, cross('UP'), seconds_until_start=12.0, contract_duration_seconds=5.0)
    assert near.decision.direction == SignalDirection.UP
    assert far.decision.direction == SignalDirection.UP
    assert far.details['threshold'] >= near.details['threshold']


def test_genuinely_flat_conflicting_market_can_still_return_no_trade():
    features = build_features(make_candles(1), make_ticks(True, flat=True))
    result = BTCFiveSecondEngine().evaluate(
        features,
        cross('NONE'),
        seconds_until_start=10.0,
        contract_duration_seconds=5.0,
    )
    assert result.decision.direction == SignalDirection.NO_TRADE


def test_wrong_contract_duration_is_rejected_before_direction():
    features = build_features(make_candles(1), make_ticks(True))
    result = BTCFiveSecondEngine().evaluate(
        features,
        cross('UP'),
        seconds_until_start=10.0,
        contract_duration_seconds=7.0,
    )
    assert result.decision.direction == SignalDirection.NO_TRADE
    assert result.details['hard_reject'] == 'contract_duration'
