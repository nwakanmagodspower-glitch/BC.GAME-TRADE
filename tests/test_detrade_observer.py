import asyncio
import base64
from datetime import datetime, timezone
import json
import time
from urllib.parse import parse_qs, urlsplit
import zlib

import pytest

import app.integrations.detrade_observer as detrade_module
from app.integrations.detrade_observer import DeTradeObserver, DeTradeRoundObservation
from app.integrations.detrade_token_provider import (
    DeTradeCredentials,
    detrade_token_is_expired,
    usable_detrade_token,
)


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


def test_connection_query_and_subscription_match_verified_browser_shape():
    observer = DeTradeObserver(FakeProvider())
    credentials = DeTradeCredentials(token='secret-value', account_type=1)
    query = parse_qs(urlsplit(observer._connection_url(credentials)).query)
    assert query == {
        'token': ['secret-value'],
        'device': ['web-pc'],
        'type': ['1'],
        'cid': [observer._browser_cid()],
    }
    message = observer._authenticated_message(
        credentials, '/contest/BTC/USD/5/ticker/subscribe'
    )
    assert set(message) == {'cmd', 'token', 'cid', 'reqId'}
    assert message['cmd'] == '/contest/BTC/USD/5/ticker/subscribe'


def test_frame_decoder_accepts_plain_json_and_raw_deflate():
    payload = {'resp': round_payload()}
    serialized = json.dumps(payload).encode()
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    raw_deflate = compressor.compress(serialized) + compressor.flush()
    assert DeTradeObserver._decode_frame(serialized) == payload
    assert DeTradeObserver._decode_frame(raw_deflate) == payload


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
    assert await observer._consume({'resp': round_payload()}) is True
    assert await observer._consume({'code': 3100, 'message': 'expired'}) is False
    assert provider.invalidated is True
    assert observer.latest is None
    assert observer._force_credential_refresh is True
    assert observer.last_error == 'DeTrade authorization expired or requires refresh.'
    assert 'secret' not in observer.last_error


def test_placeholder_credentials_are_never_created(monkeypatch):
    from app.integrations.detrade_token_provider import EnvironmentDeTradeTokenProvider
    import app.integrations.detrade_token_provider as provider_module

    monkeypatch.setattr(provider_module.settings, 'detrade_ws_token', 'temporary')
    provider = EnvironmentDeTradeTokenProvider()
    assert provider._usable_token(provider_module.settings.detrade_ws_token) is None


def _unsigned_test_jwt(exp: int) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({'exp': exp}).encode()).decode().rstrip('=')
    return f'header.{payload}.signature'


def test_expired_jwt_is_rejected_without_logging_or_signature_dependency():
    expired = _unsigned_test_jwt(1_000)
    future = _unsigned_test_jwt(3_000)

    assert detrade_token_is_expired(expired, now_seconds=2_000) is True
    assert detrade_token_is_expired(future, now_seconds=2_000) is False
    assert usable_detrade_token(expired) is None
    assert usable_detrade_token('opaque-non-placeholder-token') == 'opaque-non-placeholder-token'


@pytest.mark.asyncio
async def test_invalidated_environment_token_is_not_reused(monkeypatch):
    from app.integrations.detrade_token_provider import EnvironmentDeTradeTokenProvider
    import app.integrations.detrade_token_provider as provider_module

    monkeypatch.setattr(provider_module.settings, 'detrade_ws_token', 'real-looking-secret')
    provider = EnvironmentDeTradeTokenProvider()
    assert await provider.get_credentials() is not None
    await provider.invalidate()
    assert await provider.get_credentials(force_refresh=True) is None


def test_public_timer_state_contains_no_credentials(monkeypatch):
    monkeypatch.setattr(detrade_module.settings, 'detrade_latency_safety_margin_ms', 0)
    observation = DeTradeRoundObservation(
        round_id='round-1', status=1001, current_time_ms=10_000,
        trade_cutoff_time_ms=14_900, price_start_time_ms=15_000,
        price_end_time_ms=20_000, start_price=None, end_price=None,
        previous_round_result=None, received_monotonic=time.monotonic(),
        received_at=datetime.now(timezone.utc),
    )
    public = observation.to_public_dict()
    assert set(public) == {
        'roundId', 'status', 'phase', 'remainingMilliseconds',
        'dataAgeMilliseconds', 'canTrade', 'priceStartTime', 'priceEndTime',
    }
    assert not any('token' in key.lower() for key in public)


def test_stale_observation_is_never_tradeable(monkeypatch):
    monkeypatch.setattr(detrade_module.settings, 'detrade_stale_after_ms', 100)
    monkeypatch.setattr(detrade_module.settings, 'detrade_latency_safety_margin_ms', 0)
    observation = DeTradeRoundObservation(
        round_id='round-1', status=1001, current_time_ms=10_000,
        trade_cutoff_time_ms=19_900, price_start_time_ms=20_000,
        price_end_time_ms=25_000, start_price=None, end_price=None,
        previous_round_result=None, received_monotonic=time.monotonic() - 1,
        received_at=datetime.now(timezone.utc),
    )
    assert observation.fresh is False
    assert observation.can_trade is False


@pytest.mark.asyncio
async def test_kline_synthetic_tick_ingestion():
    observer = DeTradeObserver(FakeProvider())
    received_ticks = []
    observer.on_tick = lambda tick: received_ticks.append(tick)

    frame = {
        'resp': '/kline/BTC-USD/ticker',
        'data': [
            {'s': 'BTC-USD', 'p': '83320.12345', 't': 1790640510000, 'c': 0.1},
            {'s': 'BTC-USD', 'p': '83325.67890', 't': 1790640515000, 'c': 0.5},
        ]
    }
    handled = await observer._consume(frame)
    assert observer.latest_tick is not None
    assert observer.latest_tick['price'] == 83325.67890
    assert observer.latest_tick['timestamp_ms'] == 1790640515000
    assert len(received_ticks) == 2
    assert len(observer.bar_aggregator.get_closed_bars()) >= 1


@pytest.mark.asyncio
async def test_bootstrap_history_populates_bar_aggregator(monkeypatch):
    observer = DeTradeObserver(FakeProvider())
    mock_data = [
        {'s': 'BTC-USD', 'p': '83000.00', 't': 1790640000000, 'c': 0.0},
        {'s': 'BTC-USD', 'p': '83005.00', 't': 1790640005000, 'c': 5.0},
        {'s': 'BTC-USD', 'p': '83010.00', 't': 1790640010000, 'c': 10.0},
    ]

    class FakeResponse:
        status_code = 200
        def json(self):
            return {'code': 0, 'data': mock_data}

    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, url):
            return FakeResponse()

    monkeypatch.setattr('httpx.AsyncClient', lambda *args, **kwargs: FakeClient())

    count = await observer.bootstrap_history(seconds=120)
    assert count == 3
    assert observer.latest_tick is not None
    assert observer.latest_tick['price'] == 83010.00
    assert len(observer.bar_aggregator.get_closed_bars()) >= 2


@pytest.mark.asyncio
async def test_background_probe_wakes_immediately_on_new_observation(monkeypatch):
    monkeypatch.setattr(detrade_module.settings, 'detrade_ws_enabled', True)
    observer = DeTradeObserver(FakeProvider())

    async def running_forever():
        await asyncio.Event().wait()

    observer._task = asyncio.create_task(running_forever())

    async def publish():
        await asyncio.sleep(0.01)
        await observer._consume({'resp': round_payload()})

    publisher = asyncio.create_task(publish())
    try:
        result = await observer.probe(timeout_seconds=0.5)
        assert result is not None
        assert result.round_id == '1352602872069133'
    finally:
        await publisher
        observer._task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await observer._task

