from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.bot import signal_views
from app.models.entities import Signal, SignalDirection, SignalStatus


def button_texts(markup):
    return [button.text for row in markup.inline_keyboard for button in row]


def test_scan_prompt_requires_explicit_manual_countdown():
    texts = button_texts(signal_views.build_scan_prompt_keyboard())
    assert texts[:4] == ['15s', '14s', '13s', '12s']


def test_paper_signal_keyboard_has_no_bcgame_execution_link(monkeypatch):
    monkeypatch.setattr(signal_views.settings, 'signal_mode', 'PAPER')
    monkeypatch.setattr(signal_views, 'bcgame_adapter', SimpleNamespace(updown_url='https://bc.game/trading/up-down'))
    markup = signal_views.build_signal_keyboard(SignalDirection.UP)
    assert '🚀 Open BC.GAME Up/Down' not in button_texts(markup)


def test_live_directional_signal_can_show_bcgame_link(monkeypatch):
    monkeypatch.setattr(signal_views.settings, 'signal_mode', 'LIVE')
    monkeypatch.setattr(signal_views, 'bcgame_adapter', SimpleNamespace(updown_url='https://bc.game/trading/up-down'))
    markup = signal_views.build_signal_keyboard(SignalDirection.UP)
    assert '🚀 Open BC.GAME Up/Down' in button_texts(markup)


def test_no_trade_never_shows_bcgame_link(monkeypatch):
    monkeypatch.setattr(signal_views.settings, 'signal_mode', 'LIVE')
    monkeypatch.setattr(signal_views, 'bcgame_adapter', SimpleNamespace(updown_url='https://bc.game/trading/up-down'))
    markup = signal_views.build_signal_keyboard(SignalDirection.NO_TRADE)
    assert '🚀 Open BC.GAME Up/Down' not in button_texts(markup)


def test_paper_direction_is_explicitly_non_actionable(monkeypatch):
    monkeypatch.setattr(signal_views.settings, 'signal_mode', 'PAPER')
    now = datetime.now(timezone.utc)
    signal = Signal(
        direction=SignalDirection.UP,
        status=SignalStatus.WAITING_ENTRY,
        strategy_version='BTC_UPDOWN_5S_V1.1',
        market='BTC/USD',
        product='BC_UPDOWN_5S',
        entry_at=now + timedelta(seconds=12),
        expiry_at=now + timedelta(seconds=17),
        features_snapshot={'_bcgame_round': {'source': 'MANUAL_SYNC'}},
    )
    text = signal_views.format_signal(signal)
    assert 'Do not place a BC.GAME trade' in text
    assert 'Tap the same direction' not in text
