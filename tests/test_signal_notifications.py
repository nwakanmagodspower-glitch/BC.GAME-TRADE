from datetime import datetime, timedelta, timezone

from app.models.entities import Signal, SignalDirection, SignalStatus
from app.services import signal_notifications
from app.services.signal_notifications import SignalNotificationService


def make_signal(status: SignalStatus) -> Signal:
    now = datetime.now(timezone.utc)
    return Signal(
        id=1,
        requested_by_user_id=1,
        market='BTC/USD',
        product='BC_UPDOWN_5S',
        direction=SignalDirection.UP,
        status=status,
        strategy_version='BTC_UPDOWN_5S_V1.1',
        entry_at=now,
        expiry_at=now + timedelta(seconds=5),
        reference_entry_price=60000.0,
        reference_expiry_price=60100.0,
        decision_reason='immutable strategy reason',
        status_reason='direction inverted before start',
    )


def test_paper_active_notification_is_non_actionable(monkeypatch):
    monkeypatch.setattr(signal_notifications.settings, 'signal_mode', 'PAPER')
    service = SignalNotificationService(None)
    text = service._render(make_signal(SignalStatus.ACTIVE))
    assert 'PAPER ROUND STARTED' in text
    assert 'entry window is closed' in text
    assert 'ENTER NOW' not in text


def test_live_active_notification_is_simple_and_non_actionable(monkeypatch):
    monkeypatch.setattr(signal_notifications.settings, 'signal_mode', 'LIVE')
    service = SignalNotificationService(None)
    text = service._render(make_signal(SignalStatus.ACTIVE))
    assert 'ENTRY CLOSED' in text
    assert 'Checking the 5s result' in text
    assert 'ENTER NOW' not in text
    assert 'UP' in text
    assert 'UTC' not in text


def test_cancelled_notification_hides_internal_reason():
    service = SignalNotificationService(None)
    text = service._render(make_signal(SignalStatus.CANCELLED))
    assert 'SIGNAL CANCELLED' in text
    assert 'Market conditions changed before entry' in text
    assert 'direction inverted before start' not in text
    assert 'Skip this round' in text


def test_win_notification_is_player_friendly_and_hides_reference_prices():
    service = SignalNotificationService(None)
    text = service._render(make_signal(SignalStatus.WIN))
    assert '✅ WIN' in text
    assert 'UP' in text
    assert 'BTC/USD • 5s' in text
    assert '60,000' not in text
    assert '60,100' not in text
    assert 'External' not in text
