from datetime import datetime, timezone

from app.services.cross_venue_microstructure import CrossVenueSnapshot, VenueBookSnapshot


def _book(venue: str, bid_qty: float, ask_qty: float, depth_bid: float, depth_ask: float) -> VenueBookSnapshot:
    return VenueBookSnapshot(
        venue=venue,
        best_bid=100.0,
        best_ask=100.1,
        bid_qty=bid_qty,
        ask_qty=ask_qty,
        depth_bid_qty=depth_bid,
        depth_ask_qty=depth_ask,
        event_time=datetime.now(timezone.utc),
    )


def test_bullish_cross_venue_consensus():
    snapshot = CrossVenueSnapshot(
        binance=_book('BINANCE', 9.0, 1.0, 70.0, 30.0),
        bybit=_book('BYBIT', 8.0, 2.0, 68.0, 32.0),
    )
    assert snapshot.fresh
    assert snapshot.healthy_spread
    assert snapshot.consensus == 'UP'


def test_bearish_cross_venue_consensus():
    snapshot = CrossVenueSnapshot(
        binance=_book('BINANCE', 1.0, 9.0, 30.0, 70.0),
        bybit=_book('BYBIT', 2.0, 8.0, 32.0, 68.0),
    )
    assert snapshot.consensus == 'DOWN'


def test_disagreement_is_mixed_not_directional():
    snapshot = CrossVenueSnapshot(
        binance=_book('BINANCE', 9.0, 1.0, 70.0, 30.0),
        bybit=_book('BYBIT', 1.0, 9.0, 30.0, 70.0),
    )
    assert snapshot.consensus == 'MIXED'
