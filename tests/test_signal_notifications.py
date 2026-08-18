from datetime import datetime, timedelta, timezone

from app.models.entities import Signal, SignalDirection, SignalStatus
from app.services.signal_notifications import SignalNotificationService


def make_signal(status: SignalStatus) -> Signal:
    now = datetime.now(timezone.utc)
    return Signal(
        id=1,
        requested_by_user_id=1,
        market='BTCUSDT',
        product='BC_UPDOWN',
        direction=SignalDirection.UP,
        status=status,
        strategy_version='BTC_UPDOWN_V1.0',
        entry_at=now,
        expiry_at=now + timedelta(minutes=5),
        reference_entry_price=60000.0,
        reference_expiry_price=60100.0,
        decision_reason='test reason',
    )


def test_active_notification_is_enter_now():
    service = SignalNotificationService(None)
    text, _ = service._render(make_signal(SignalStatus.ACTIVE))
    assert 'ENTER NOW' in text
    assert 'UP' in text


def test_cancelled_notification_says_do_not_enter():
    service = SignalNotificationService(None)
    text, keyboard = service._render(make_signal(SignalStatus.CANCELLED))
    assert 'SIGNAL CANCELLED' in text
    assert 'Do not enter' in text
    assert keyboard is None


def test_win_notification_contains_reference_prices():
    service = SignalNotificationService(None)
    text, _ = service._render(make_signal(SignalStatus.WIN))
    assert 'SIGNAL RESULT — WIN' in text
    assert '60,000.00' in text
    assert '60,100.00' in text
