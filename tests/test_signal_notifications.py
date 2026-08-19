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
        status_reason='test status reason',
    )


def test_paper_active_notification_is_non_actionable(monkeypatch):
    monkeypatch.setattr(signal_notifications.settings, 'signal_mode', 'PAPER')
    service = SignalNotificationService(None)
    text = service._render(make_signal(SignalStatus.ACTIVE))
    assert 'PAPER ROUND STARTED' in text
    assert 'order window is already closed' in text
    assert 'ENTER NOW' not in text


def test_live_active_notification_prohibits_late_entry(monkeypatch):
    monkeypatch.setattr(signal_notifications.settings, 'signal_mode', 'LIVE')
    service = SignalNotificationService(None)
    text = service._render(make_signal(SignalStatus.ACTIVE))
    assert 'Do not attempt a late order' in text
    assert 'ENTER NOW' not in text
    assert 'UP' in text


def test_cancelled_notification_says_do_not_enter():
    service = SignalNotificationService(None)
    text = service._render(make_signal(SignalStatus.CANCELLED))
    assert 'SIGNAL CANCELLED' in text
    assert 'test status reason' in text


def test_win_notification_contains_reference_prices():
    service = SignalNotificationService(None)
    text = service._render(make_signal(SignalStatus.WIN))
    assert 'SIGNAL RESULT — WIN' in text
    assert '60,000.00' in text
    assert '60,100.00' in text
