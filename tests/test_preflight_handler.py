from types import SimpleNamespace

import pytest

from app.bot import preflight_handler
from app.integrations.bcgame_rounds import BCGameRoundDecision


class DummySession:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class DummyChat:
    type = 'private'
    id = 42

    def __init__(self):
        self.messages: list[str] = []

    async def send_message(self, text: str):
        self.messages.append(text)


@pytest.mark.asyncio
async def test_owner_preflight_reports_ready_only_for_safe_synchronized_path(monkeypatch):
    chat = DummyChat()
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42),
        effective_chat=chat,
    )
    monkeypatch.setattr(preflight_handler.settings, 'owner_telegram_id', 42)
    monkeypatch.setattr(preflight_handler.settings, 'signal_mode', 'LIVE')
    monkeypatch.setattr(preflight_handler.settings, 'signal_timing_mode', 'HYBRID_SYNC')
    monkeypatch.setattr(preflight_handler, 'SessionLocal', lambda: DummySession())
    monkeypatch.setattr(
        preflight_handler.AdminOpsService,
        'get_bool',
        lambda _self, _key, default: True,
    )

    snapshot = SimpleNamespace(fresh=True, age_seconds=0.1)

    async def get_snapshot(*_args):
        return snapshot

    async def get_candles(*_args):
        return [object()]

    async def refresh_age(*_args):
        return 0.2

    async def trade_metrics(*_args):
        return 150, 14.8

    async def round_decision():
        return BCGameRoundDecision(
            synchronized=True,
            actionable=True,
            snapshot=None,
            reason='safe',
            remaining_seconds=12.0,
        )

    monkeypatch.setattr(preflight_handler.market_data_service.cache, 'get_snapshot', get_snapshot)
    monkeypatch.setattr(preflight_handler.market_data_service, 'get_cached_candles', get_candles)
    monkeypatch.setattr(
        preflight_handler.market_data_service.cache,
        'get_candle_refresh_age_seconds',
        refresh_age,
    )
    monkeypatch.setattr(
        preflight_handler.market_data_service.cache,
        'get_trade_window_metrics',
        trade_metrics,
    )
    monkeypatch.setattr(
        preflight_handler.bcgame_round_service,
        'current_round_decision',
        round_decision,
    )

    await preflight_handler.preflight_command(update, SimpleNamespace())

    assert len(chat.messages) == 1
    assert 'READY TO SCAN' in chat.messages[0]
    assert 'SYNCED — 12.00s remaining' in chat.messages[0]
    assert 'may still return NO TRADE' in chat.messages[0]
