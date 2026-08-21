from datetime import datetime, timezone
import time

import pytest

import app.integrations.bcgame_rounds as round_module
from app.integrations.bcgame_rounds import BCGameRoundService
from app.integrations.detrade_observer import DeTradeRoundObservation


def observation(*, status=1001, remaining_ms=12_000):
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = now_ms + remaining_ms
    return DeTradeRoundObservation(
        round_id='round-verified-1',
        status=status,
        current_time_ms=now_ms,
        trade_cutoff_time_ms=start_ms - 100,
        price_start_time_ms=start_ms,
        price_end_time_ms=start_ms + 5000,
        start_price=None,
        end_price=None,
        previous_round_result=None,
        received_monotonic=time.monotonic(),
        received_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_safe_verified_round_becomes_actionable(monkeypatch):
    monkeypatch.setattr(round_module.settings, 'bcgame_round_sync_enabled', True)
    monkeypatch.setattr(round_module.settings, 'detrade_ws_enabled', True)
    monkeypatch.setattr(round_module.settings, 'detrade_ws_token', 'secret')
    monkeypatch.setattr(round_module.settings, 'detrade_latency_safety_margin_ms', 7000)

    async def fake_probe(timeout_seconds=None):
        return observation(status=1001, remaining_ms=12_000)

    monkeypatch.setattr(round_module.detrade_observer, 'probe', fake_probe)
    decision = await BCGameRoundService().current_round_decision()

    assert decision.synchronized is True
    assert decision.actionable is True
    assert decision.snapshot is not None
    assert decision.snapshot.source == 'DETRADE_SYNC'
    assert decision.snapshot.round_id == 'round-verified-1'
    assert decision.remaining_seconds is not None and decision.remaining_seconds > 11


@pytest.mark.asyncio
async def test_known_closed_round_never_falls_through_as_actionable(monkeypatch):
    monkeypatch.setattr(round_module.settings, 'bcgame_round_sync_enabled', True)
    monkeypatch.setattr(round_module.settings, 'detrade_ws_enabled', True)
    monkeypatch.setattr(round_module.settings, 'detrade_ws_token', 'secret')

    async def fake_probe(timeout_seconds=None):
        return observation(status=1003, remaining_ms=0)

    monkeypatch.setattr(round_module.detrade_observer, 'probe', fake_probe)
    decision = await BCGameRoundService().current_round_decision()

    assert decision.synchronized is True
    assert decision.actionable is False
    assert decision.snapshot is None
    assert 'not accepting entries' in decision.reason


@pytest.mark.asyncio
async def test_unconfigured_feed_is_distinguishable_from_known_unsafe_round(monkeypatch):
    monkeypatch.setattr(round_module.settings, 'bcgame_round_sync_enabled', True)
    monkeypatch.setattr(round_module.settings, 'detrade_ws_enabled', False)
    decision = await BCGameRoundService().current_round_decision()

    assert decision.synchronized is False
    assert decision.actionable is False
    assert decision.snapshot is None
