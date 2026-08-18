from app.bot import signal_views
from app.models.entities import SignalDirection


def button_texts(markup):
    return [button.text for row in markup.inline_keyboard for button in row]


def test_scan_prompt_requires_explicit_scan_now():
    texts = button_texts(signal_views.build_scan_prompt_keyboard())
    assert '🔍 Scan Now' in texts


def test_paper_signal_keyboard_has_no_bcgame_execution_link(monkeypatch):
    monkeypatch.setattr(signal_views.settings, 'signal_mode', 'PAPER')
    monkeypatch.setattr(signal_views.settings, 'bcgame_updown_url', 'https://example.com/updown')
    markup = signal_views.build_signal_keyboard(SignalDirection.UP)
    assert '🚀 Open BC.GAME Up/Down' not in button_texts(markup)


def test_live_directional_signal_can_show_bcgame_link(monkeypatch):
    monkeypatch.setattr(signal_views.settings, 'signal_mode', 'LIVE')
    monkeypatch.setattr(signal_views.settings, 'bcgame_updown_url', 'https://example.com/updown')
    markup = signal_views.build_signal_keyboard(SignalDirection.UP)
    assert '🚀 Open BC.GAME Up/Down' in button_texts(markup)


def test_no_trade_never_shows_bcgame_link(monkeypatch):
    monkeypatch.setattr(signal_views.settings, 'signal_mode', 'LIVE')
    monkeypatch.setattr(signal_views.settings, 'bcgame_updown_url', 'https://example.com/updown')
    markup = signal_views.build_signal_keyboard(SignalDirection.NO_TRADE)
    assert '🚀 Open BC.GAME Up/Down' not in button_texts(markup)
