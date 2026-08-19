from datetime import datetime, timedelta, timezone

import pytest

from app.integrations.bcgame_rounds import BCGameRoundService


def test_manual_timing_uses_confirmed_countdown_and_five_second_contract():
    observed = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)
    snapshot = BCGameRoundService().manual_snapshot(15, observed_at=observed)

    assert snapshot.source == 'MANUAL_SYNC'
    assert snapshot.order_closes_at == observed + timedelta(seconds=15)
    assert snapshot.start_rate_at == snapshot.order_closes_at
    assert snapshot.end_rate_at == snapshot.start_rate_at + timedelta(seconds=5)
    assert snapshot.seconds_until_order_close(observed + timedelta(seconds=3)) == 12
    assert snapshot.round_id.startswith('manual-')


def test_manual_timing_rejects_unsupported_countdown():
    with pytest.raises(ValueError):
        BCGameRoundService().manual_snapshot(11)
