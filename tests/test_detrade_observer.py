from datetime import datetime, timezone
import time

import app.integrations.detrade_observer as detrade_module
from app.integrations.detrade_observer import DeTradeObserver, DeTradeRoundObservation


def round_payload(status=1001):
    return {
        'id': '1352602872069133',
        'status': status,
        'currentTime': 1_000_000,
        'tradeCutoffTime': 1_014_900,
        'priceStartTime': 1_015_000,
        'priceEndTime': 1_020_000,
        'startPrice': 77200.5,
        'endPrice': None,
    }


def test_verified_subscription_is_zlib_wrapped_and_contains_token(monkeypatch):
    observer = DeTradeObserver()
    monkeypatch.setattr(detrade_module.settings, 'detrade_ws_token', 'secret')
    encoded = observer._encode_message(observer._subscription_message())
    decoded = observer._decode_frame(encoded)
    assert decoded['cmd'] == '/contest/BTC/USD/5/ticker/subscribe'
    assert decoded['token'] == 'secret'
    assert decoded['cid']
    assert decoded['reqId']


def test_price_start_time_is_authoritative_countdown_boundary(monkeypatch):
    monkeypatch.setattr(detrade_module.settings, 'detrade_latency_safety_margin_ms', 1000)
    observation = DeTradeRoundObservation(
        round_id='round-1',
        status=1001,
        current_time_ms=10_000,
        trade_cutoff_time_ms=14_000,
        price_start_time_ms=15_000,
        price_end_time_ms=20_000,
        start_price=None,
        end_price=None,
        previous_round_result=None,
        received_monotonic=time.monotonic(),
        received_at=datetime.now(timezone.utc),
    )
    assert observation.authoritative_cutoff_ms == 15_000
    assert 4_800 <= observation.remaining_ms <= 5_000
    assert observation.can_trade


def test_unknown_and_1008_are_non_tradeable(monkeypatch):
    monkeypatch.setattr(detrade_module.settings, 'detrade_latency_safety_margin_ms', 0)
    for status in (1002, 1003, 1004, 1005, 1006, 1007, 1008, 9999):
        observation = DeTradeRoundObservation(
            round_id='round-1',
            status=status,
            current_time_ms=10_000,
            trade_cutoff_time_ms=14_900,
            price_start_time_ms=15_000,
            price_end_time_ms=20_000,
            start_price=None,
            end_price=None,
            previous_round_result=None,
            received_monotonic=time.monotonic(),
            received_at=datetime.now(timezone.utc),
        )
        assert observation.can_trade is False


def test_consume_verified_round_payload():
    observer = DeTradeObserver()
    assert observer._consume({'resp': round_payload()}) is True
    assert observer.latest is not None
    assert observer.latest.round_id == '1352602872069133'
    assert observer.latest.phase == 'BETTING'
    assert observer.latest.price_end_time_ms - observer.latest.price_start_time_ms == 5000


def test_auth_failure_is_redacted():
    observer = DeTradeObserver()
    assert observer._consume({'code': 3100, 'message': 'expired'}) is False
    assert observer.last_error == 'DeTrade authentication refresh is required.'
    assert 'token' not in observer.last_error.lower()
