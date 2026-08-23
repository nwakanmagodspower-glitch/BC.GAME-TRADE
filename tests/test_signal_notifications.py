from datetime import datetime, timedelta, timezone

import pytest

from app.models.entities import Signal, SignalDirection, SignalStatus
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'status',
    [
        SignalStatus.ACTIVE,
        SignalStatus.CANCELLED,
        SignalStatus.EXPIRED,
        SignalStatus.WIN,
        SignalStatus.LOSS,
        SignalStatus.TIE,
    ],
)
async def test_lifecycle_notifications_remain_disabled(status):
    service = SignalNotificationService(None)
    assert await service.notify_status(make_signal(status)) is False
