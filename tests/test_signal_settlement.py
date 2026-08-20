from datetime import datetime, timedelta, timezone

import pytest

from app.models.entities import Signal, SignalDirection, SignalStatus
from app.services.market_data import MarketSnapshot, market_data_service
from app.services.signal_lifecycle import SignalLifecycleService


class DummyDB:
    def commit(self):
        pass

    def refresh(self, obj):
        pass


@pytest.mark.asyncio
async def test_up_signal_wins_when_expiry_is_higher(monkeypatch):
    now = datetime.now(timezone.utc)
    signal = Signal(
        direction=SignalDirection.UP,
        status=SignalStatus.ACTIVE,
        market='BTCUSDT',
        strategy_version='TEST',
        decision_reason='Original strategy rationale',
        reference_entry_price=100.0,
        expiry_at=now - timedelta(seconds=1),
    )

    async def snapshot(*args, **kwargs):
        return MarketSnapshot('BTCUSDT', 101.0, now, 'TEST', 0.0, True, 0.0, None)

    monkeypatch.setattr(market_data_service.cache, 'get_snapshot', snapshot)
    result = await SignalLifecycleService(DummyDB()).settle_if_due(signal, now=now)
    assert result.status == SignalStatus.WIN
    assert result.reference_expiry_price == 101.0
    assert result.decision_reason == 'Original strategy rationale'
    assert 'External-reference UP' in result.status_reason


@pytest.mark.asyncio
async def test_down_signal_loses_when_expiry_is_higher(monkeypatch):
    now = datetime.now(timezone.utc)
    signal = Signal(
        direction=SignalDirection.DOWN,
        status=SignalStatus.ACTIVE,
        market='BTCUSDT',
        strategy_version='TEST',
        reference_entry_price=100.0,
        expiry_at=now - timedelta(seconds=1),
    )

    async def snapshot(*args, **kwargs):
        return MarketSnapshot('BTCUSDT', 101.0, now, 'TEST', 0.0, True, 0.0, None)

    monkeypatch.setattr(market_data_service.cache, 'get_snapshot', snapshot)
    result = await SignalLifecycleService(DummyDB()).settle_if_due(signal, now=now)
    assert result.status == SignalStatus.LOSS


@pytest.mark.asyncio
async def test_equal_price_follows_down_wins_rule(monkeypatch):
    now = datetime.now(timezone.utc)

    async def snapshot(*args, **kwargs):
        return MarketSnapshot('BTCUSDT', 100.0, now, 'TEST', 0.0, True, 0.0, None)

    monkeypatch.setattr(market_data_service.cache, 'get_snapshot', snapshot)

    up_signal = Signal(
        direction=SignalDirection.UP,
        status=SignalStatus.ACTIVE,
        market='BTCUSDT',
        strategy_version='TEST',
        reference_entry_price=100.0,
        expiry_at=now - timedelta(seconds=1),
    )
    down_signal = Signal(
        direction=SignalDirection.DOWN,
        status=SignalStatus.ACTIVE,
        market='BTCUSDT',
        strategy_version='TEST',
        reference_entry_price=100.0,
        expiry_at=now - timedelta(seconds=1),
    )

    up_result = await SignalLifecycleService(DummyDB()).settle_if_due(up_signal, now=now)
    down_result = await SignalLifecycleService(DummyDB()).settle_if_due(down_signal, now=now)
    assert up_result.status == SignalStatus.LOSS
    assert down_result.status == SignalStatus.WIN
