import asyncio
from datetime import datetime, timezone
import time

import app.integrations.bcgame_rounds as round_module
from app.integrations.bcgame_rounds import BCGameRoundService
from app.integrations.detrade_observer import DeTradeRoundObservation


def observation(*, status=1001, remaining_ms=12_000, evaluation_ms=5_000):
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = now_ms + remaining_ms
    return DeTradeRoundObservation(
        round_id='round-verified-1',
        status=status,
        current_time_ms=now_ms,
        trade_cutoff_time_ms=start_ms - 100,
        price_start_time_ms=start_ms,
        price_end_time_ms=start_ms + evaluation_ms,
        start_price=None,
        end_price=None,
        previous_round_result=None,
        received_monotonic=time.monotonic(),
        received_at=datetime.now(timezone.utc),
    )


def _prepare(monkeypatch):
    monkeypatch.setattr(round_module.settings, 'bcgame_round_sync_enabled', True)
    monkeypatch.setattr(round_module.settings, 'detrade_ws_enabled', True)
    monkeypatch.setattr(round_module.settings, 'detrade_ws_token', 'secret')
    monkeypatch.setattr(round_module.settings, 'detrade_latency_safety_margin_ms', 7000)
    round_module.detrade_observer.latest = None


def test_safe_verified_round_becomes_actionable(monkeypatch):
    _prepare(monkeypatch)

    async def fake_probe(timeout_seconds=None):
        return observation(status=1001, remaining_ms=12_000)

    monkeypatch.setattr(round_module.detrade_observer, 'probe', fake_probe)
    decision = asyncio.run(BCGameRoundService().current_round_decision())

    assert decision.synchronized is True
    assert decision.actionable is True
    assert decision.snapshot is not None
    assert decision.snapshot.source == 'DETRADE_SYNC'
    assert decision.snapshot.round_id == 'round-verified-1'
    assert decision.remaining_seconds is not None and decision.remaining_seconds > 11


def test_five_second_round_allows_small_server_timestamp_variation(monkeypatch):
    _prepare(monkeypatch)

    for evaluation_ms in (4_999, 5_001, 4_500, 5_500):
        async def fake_probe(timeout_seconds=None, duration=evaluation_ms):
            return observation(status=1001, remaining_ms=12_000, evaluation_ms=duration)

        monkeypatch.setattr(round_module.detrade_observer, 'probe', fake_probe)
        round_module.detrade_observer.latest = None
        decision = asyncio.run(BCGameRoundService().current_round_decision())
        assert decision.synchronized is True
        assert decision.actionable is True


def test_known_closed_round_never_falls_through_as_actionable(monkeypatch):
    _prepare(monkeypatch)

    async def fake_probe(timeout_seconds=None):
        return observation(status=1003, remaining_ms=0)

    monkeypatch.setattr(round_module.detrade_observer, 'probe', fake_probe)
    decision = asyncio.run(BCGameRoundService().current_round_decision())

    assert decision.synchronized is True
    assert decision.actionable is False
    assert decision.snapshot is None
    assert 'not accepting entries' in decision.reason


def test_unconfigured_feed_is_distinguishable_from_known_unsafe_round(monkeypatch):
    monkeypatch.setattr(round_module.settings, 'bcgame_round_sync_enabled', True)
    monkeypatch.setattr(round_module.settings, 'detrade_ws_enabled', False)
    decision = asyncio.run(BCGameRoundService().current_round_decision())

    assert decision.synchronized is False
    assert decision.actionable is False
    assert decision.snapshot is None


def test_late_and_wrong_contract_rounds_fail_closed(monkeypatch):
    _prepare(monkeypatch)
    monkeypatch.setattr(round_module.settings, 'detrade_latency_safety_margin_ms', 10_000)

    service = BCGameRoundService()

    async def late_probe(timeout_seconds=None):
        return observation(remaining_ms=9_000)

    monkeypatch.setattr(round_module.detrade_observer, 'probe', late_probe)
    late = asyncio.run(service.current_round_decision())
    assert late.synchronized and not late.actionable
    assert 'too close' in late.reason

    round_module.detrade_observer.latest = None

    async def wrong_contract_probe(timeout_seconds=None):
        return observation(remaining_ms=12_000, evaluation_ms=8_000)

    monkeypatch.setattr(round_module.detrade_observer, 'probe', wrong_contract_probe)
    wrong = asyncio.run(service.current_round_decision())
    assert wrong.synchronized and not wrong.actionable
    assert '5-second contract' in wrong.reason


def test_concurrent_round_requests_share_one_probe(monkeypatch):
    monkeypatch.setattr(round_module.settings, 'detrade_probe_coalesce_ms', 300)
    round_module.detrade_observer.latest = None
    calls = 0

    async def fake_probe(timeout_seconds=None):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        result = observation()
        round_module.detrade_observer.latest = result
        return result

    monkeypatch.setattr(round_module.detrade_observer, 'probe', fake_probe)
    service = BCGameRoundService()

    async def run():
        return await asyncio.gather(service._fresh_observation(), service._fresh_observation())

    results = asyncio.run(run())
    assert calls == 1
    assert results[0] is results[1]
    round_module.detrade_observer.latest = None
