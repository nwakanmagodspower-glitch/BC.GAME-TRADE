from datetime import datetime, timezone
import time
import zlib

import pytest

import app.integrations.detrade_observer as detrade_module
from app.integrations.detrade_observer import DeTradeObserver, DeTradeRoundObservation
from app.integrations.detrade_token_provider import DeTradeCredentials


class FakeProvider:
    def __init__(self, token='secret', account_type=1):
        self.credentials = DeTradeCredentials(token=token, account_type=account_type) if token else None
        self.invalidated = False

    async def get_credentials(self, *, force_refresh=False):
        if self.invalidated and not force_refresh:
            return None
        return self.credentials

    async def invalidate(self):
        self.invalidated = True


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


def test_verified_subscription_and_ping_are_zlib_wrapped(monkeypatch):
    observer = DeTradeObserver(FakeProvider())
    credentials = DeTradeCredentials(token='secret', account_type=1)
    for command in ('/contest/BTC/USD/5/ticker/subscribe', 'ping'):
        encoded = observer._encode_message(observer._authenticated_message(credentials, command))
        decoded = observer._decode_frame(encoded)
        assert decoded['cmd'] == command
        assert decoded['token'] == 'secret'
        assert decoded['cid']
        assert decoded['reqId']
        assert zlib.decompress(encoded)


def test_price_start_time_is_authoritative_countdown_boundary(monkeypatch):
    monkeypatch.setattr(detrade_module.settings, 'detrade_latency_safety_margin_ms', 1000)
    observation = DeTradeRoundObservation(
        round_id='round-1', status=1001, current_time_ms=10_000,
        trade_cutoff_time_ms=14_000, price_start_time_ms=15_000,
        price_end_time_ms=20_000, start_price=None, end_price=None,
        previous_round_result=None, received_monotonic=time.monotonic(),
        received_at=datetime.now(timezone.utc),
    )
    assert observation.authoritative_cutoff_ms == 15_000
    assert 4_800 <= observation.remaining_ms <= 5_000
    assert observation.can_trade


def test_unknown_and_1008_are_non_tradeable(monkeypatch):
    monkeypatch.setattr(detrade_module.settings, 'detrade_latency_safety_margin_ms', 0)
    for status in (1002, 1003, 1004, 1005, 1006, 1007, 1008, 9999):
        observation = DeTradeRoundObservation(
            round_id='round-1', status=status, current_time_ms=10_000,
            trade_cutoff_time_ms=14_900, price_start_time_ms=15_000,
            price_end_time_ms=20_000, start_price=None, end_price=None,
            previous_round_result=None, received_monotonic=time.monotonic(),
            received_at=datetime.now(timezone.utc),
        )
        assert observation.can_trade is False


@pytest.mark.asyncio
async def test_consume_verified_round_payload():
    observer = DeTradeObserver(FakeProvider())
    assert await observer._consume({'resp': round_payload()}) is True
    assert observer.latest is not None
    assert observer.latest.round_id == '1352602872069133'
    assert observer.latest.phase == 'BETTING'
    assert observer.latest.price_end_time_ms - observer.latest.price_start_time_ms == 5000


@pytest.mark.asyncio
async def test_auth_failure_invalidates_provider_without_leaking_secret():
    provider = FakeProvider()
    observer = DeTradeObserver(provider)
    assert await observer._consume({'code': 3100, 'message': 'expired'}) is False
    assert provider.invalidated is True
    assert observer.last_error == 'DeTrade authorization expired or requires refresh.'
    assert 'secret' not in observer.last_error


def test_placeholder_credentials_are_never_created(monkeypatch):
    from app.integrations.detrade_token_provider import EnvironmentDeTradeTokenProvider
    import app.integrations.detrade_token_provider as provider_module

    monkeypatch.setattr(provider_module.settings, 'detrade_ws_token', 'temporary')
    provider = EnvironmentDeTradeTokenProvider()
    assert provider._usable_token(provider_module.settings.detrade_ws_token) is None
