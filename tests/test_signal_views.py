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

def test_no_trade_round_already_started():
    signal = Signal(
        direction=SignalDirection.NO_TRADE,
        status=SignalStatus.NO_TRADE,
        status_reason='This round has already started. Wait for the new countdown and tap Scan.',
        strategy_version='BTC_ORIGINAL_INTELLIGENCE_TIMER_V1',
        market='BTC/USD',
        product='BC_UPDOWN_5S',
    )
    text = signal_views.format_signal(signal)
    assert '⚪ NO TRADE — Round Already Started' in text
    assert 'The round countdown has already reached 0:00' in text
    assert 'Wait for the next round countdown' in text


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
    assert 'Wait for clear momentum that aligns with the broader trend.' in text
    assert 'Preserve capital' not in text


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
                'stake_recommendation': '🔥 Stake High',
            },
            'lead_range_dollars': 12.5,
        },
    )
    text_prime = signal_views.format_signal(signal_prime)
    assert '🟢 UP SIGNAL' in text_prime
    assert 'STRONG' in text_prime
    # Verify no trade amount or percentage is recommended on any signal
    assert 'Recommended Trade Size' not in text_prime
    assert 'Recommended Stake' not in text_prime
    assert '2%' not in text_prime
    assert '5%' not in text_prime

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
                'stake_recommendation': '⚡ Stake Low',
            },
            'lead_range_dollars': 5.0,
        },
    )
    text_std = signal_views.format_signal(signal_std)
    assert 'Stake Low' not in text_std
    assert 'DOWN SIGNAL' in text_std


def test_signal_views_no_directional_contradictions():
    # UP signal must never have "Down" in its tag
    decision_up = {
        'quality': 'STRONG',
        'ai_prediction': {'confidence_pct': 85, 'ai_regime': 'EXHAUSTION_TOP'},
    }
    tag_up = signal_views._format_confidence_tag(decision_up, direction=SignalDirection.UP)
    assert 'Down' not in tag_up
    assert 'UP' not in tag_up.lower() or 'up' in tag_up.lower()
    assert '85%' in tag_up or '95%' in tag_up

    # DOWN signal must never have "Up" in its tag
    decision_down = {
        'quality': 'STRONG',
        'ai_prediction': {'confidence_pct': 85, 'ai_regime': 'EXHAUSTION_BOTTOM'},
    }
    tag_down = signal_views._format_confidence_tag(decision_down, direction=SignalDirection.DOWN)
    assert 'Up' not in tag_down
    assert '85%' in tag_down or '95%' in tag_down


def test_signal_views_confidence_never_zero_or_neutral():
    decision_zero = {
        'quality': 'STRONG',
        'ai_prediction': {'confidence_pct': 0, 'ai_regime': 'NEUTRAL'},
    }
    tag = signal_views._format_confidence_tag(decision_zero, direction=SignalDirection.UP)
    assert '0%' not in tag
    assert 'Neutral' not in tag
    assert '95%' in tag

    decision_low = {
        'quality': 'CONFIRMED',
        'ai_prediction': {'confidence_pct': 51, 'ai_regime': 'MICRO_CHOP'},
    }
    tag_low = signal_views._format_confidence_tag(decision_low, direction=SignalDirection.DOWN)
    assert '51%' not in tag_low
    assert 'Chop' not in tag_low
    assert '85%' in tag_low


def test_build_signal_keyboard_separate_rows(monkeypatch):
    monkeypatch.setattr(signal_views.settings, 'signal_mode', 'LIVE')
    monkeypatch.setattr(signal_views, 'bcgame_adapter', SimpleNamespace(updown_url='https://bc.game/trading/up-down'))
    markup = signal_views.build_signal_keyboard(SignalDirection.UP, signal_id=99)
    assert len(markup.inline_keyboard) == 3
    assert markup.inline_keyboard[0][0].text == '🚀 Open BCGAME Up/Down'
    assert markup.inline_keyboard[1][0].text == '⚡ Scan Market'
    assert markup.inline_keyboard[2][0].text == '🏆 Won Round (+1 Win)'



