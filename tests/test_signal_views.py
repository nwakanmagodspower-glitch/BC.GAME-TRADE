from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.bot import signal_views
from app.models.entities import Signal, SignalDirection, SignalStatus


def button_texts(markup):
    return [button.text for row in markup.inline_keyboard for button in row]


def test_scan_prompt_uses_single_scan_now_action(monkeypatch):
    monkeypatch.setattr(signal_views, 'bcgame_adapter', SimpleNamespace(updown_url='https://bc.game/trading/up-down'))
    texts = button_texts(signal_views.build_scan_prompt_keyboard())
    assert texts == ['🚀 Open BCGAME Up/Down', '⚡ Scan Market']
    assert not any(text in texts for text in ('15s', '14s', '13s', '12s'))


def test_paper_signal_keyboard_has_no_bcgame_execution_link(monkeypatch):
    monkeypatch.setattr(signal_views.settings, 'signal_mode', 'PAPER')
    monkeypatch.setattr(signal_views, 'bcgame_adapter', SimpleNamespace(updown_url='https://bc.game/trading/up-down'))
    markup = signal_views.build_signal_keyboard(SignalDirection.UP)
    assert '🚀 Open BCGAME Up/Down' not in button_texts(markup)


def test_live_directional_signal_can_show_bcgame_link(monkeypatch):
    monkeypatch.setattr(signal_views.settings, 'signal_mode', 'LIVE')
    monkeypatch.setattr(signal_views, 'bcgame_adapter', SimpleNamespace(updown_url='https://bc.game/trading/up-down'))
    markup = signal_views.build_signal_keyboard(SignalDirection.UP)
    assert '🚀 Open BCGAME Up/Down' in button_texts(markup)


def test_no_trade_never_shows_bcgame_link(monkeypatch):
    monkeypatch.setattr(signal_views.settings, 'signal_mode', 'LIVE')
    monkeypatch.setattr(signal_views, 'bcgame_adapter', SimpleNamespace(updown_url='https://bc.game/trading/up-down'))
    markup = signal_views.build_signal_keyboard(SignalDirection.NO_TRADE)
    assert '🚀 Open BCGAME Up/Down' not in button_texts(markup)


def test_synchronized_signal_hides_round_id_and_keeps_simple_entry_window(monkeypatch):
    monkeypatch.setattr(signal_views.settings, 'signal_mode', 'LIVE')
    now = datetime.now(timezone.utc)
    signal = Signal(
        direction=SignalDirection.UP,
        status=SignalStatus.WAITING_ENTRY,
        strategy_version='BTC_UPDOWN_5S_V1.1',
        market='BTC/USD',
        product='BC_UPDOWN_5S',
        entry_at=now + timedelta(seconds=12),
        expiry_at=now + timedelta(seconds=17),
        features_snapshot={
            '_decision': {'quality': 'STRONG'},
            '_bcgame_round': {
                'source': 'DETRADE_SYNC',
                'round_id': '1352602872069133',
                'remaining_seconds_at_scan': 12.4,
            },
        },
    )
    text = signal_views.format_signal(signal)
    assert '🟢 UP' in text
    assert '🔥 Strength: STRONG' in text
    assert 'Entry window: ~12.4s' in text
    assert '1352602872069133' not in text
    assert 'Timing: synchronized' not in text
    assert 'Round:' not in text


def test_no_trade_message_is_simple():
    signal = Signal(
        direction=SignalDirection.NO_TRADE,
        status=SignalStatus.NO_TRADE,
        strategy_version='BTC_UPDOWN_5S_V1.1',
        market='BTC/USD',
        product='BC_UPDOWN_5S',
    )
    text = signal_views.format_signal(signal)
    assert '⚪ NO TRADE' in text
    assert 'No qualified setup right now' in text
    assert 'Timing:' not in text
    assert 'Round:' not in text


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
    assert 'Recorded for PAPER validation only.' in text
    assert 'Open BCGAME and place' not in text

def test_no_trade_late_entry_window():
    signal = Signal(
        direction=SignalDirection.NO_TRADE,
        status=SignalStatus.NO_TRADE,
        status_reason='Entry window too short (< 8s remaining: 5.2s). Skip round to avoid late entry risk.',
        strategy_version='BTC_ORIGINAL_INTELLIGENCE_TIMER_V1',
        market='BTC/USD',
        product='BC_UPDOWN_5S',
    )
    text = signal_views.format_signal(signal)
    assert '⚪ NO TRADE — Late Entry Window' in text
    assert 'Less than 8.0s remaining before round starts' in text
    assert 'Wait for the next round' in text


def test_no_trade_macro_trend_conflict():
    signal = Signal(
        direction=SignalDirection.NO_TRADE,
        status=SignalStatus.NO_TRADE,
        status_reason='Macro 1m trend conflict: Bullish 5s setup vetoed by deep 1m downward trend (EMA cascade down and RSI 38.2)',
        strategy_version='BTC_ORIGINAL_INTELLIGENCE_TIMER_V1',
        market='BTC/USD',
        product='BC_UPDOWN_5S',
    )
    text = signal_views.format_signal(signal)
    assert '⚪ NO TRADE — Trend Conflict' in text
    assert 'Short-term tick contradicts macro 1-minute trend' in text
    assert 'Preserve capital' in text


def test_directional_signal_dynamic_stake_guidance(monkeypatch):
    monkeypatch.setattr(signal_views.settings, 'signal_mode', 'LIVE')
    now = datetime.now(timezone.utc)
    signal_prime = Signal(
        direction=SignalDirection.UP,
        status=SignalStatus.WAITING_ENTRY,
        strategy_version='BTC_ORIGINAL_INTELLIGENCE_TIMER_V1',
        market='BTC/USD',
        product='BC_UPDOWN_5S',
        entry_at=now + timedelta(seconds=12),
        expiry_at=now + timedelta(seconds=17),
        features_snapshot={
            '_decision': {
                'quality': 'STRONG',
                'bull_score': 8,
                'bear_score': 0,
                'stake_recommendation': '🔥 PRIME SETUP (Full allocation: 2%–3% of bankroll)',
            },
            'lead_range_dollars': 12.5,
        },
    )
    text_prime = signal_views.format_signal(signal_prime)
    assert '🎯 Stake Guidance: 🔥 PRIME SETUP (Full allocation: 2%–3% of bankroll)' in text_prime

    signal_std = Signal(
        direction=SignalDirection.DOWN,
        status=SignalStatus.WAITING_ENTRY,
        strategy_version='BTC_ORIGINAL_INTELLIGENCE_TIMER_V1',
        market='BTC/USD',
        product='BC_UPDOWN_5S',
        entry_at=now + timedelta(seconds=12),
        expiry_at=now + timedelta(seconds=17),
        features_snapshot={
            '_decision': {
                'quality': 'CONFIRMED',
                'bull_score': 1,
                'bear_score': 5,
                'stake_recommendation': '⚡ STANDARD SETUP (Base allocation: 1%–1.5% of bankroll)',
            },
            'lead_range_dollars': 5.0,
        },
    )
    text_std = signal_views.format_signal(signal_std)
    assert '🎯 Stake Guidance: ⚡ STANDARD SETUP (Base allocation: 1%–1.5% of bankroll)' in text_std

