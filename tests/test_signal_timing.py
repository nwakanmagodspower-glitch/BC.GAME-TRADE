from datetime import datetime, timezone

from app.signals.timing import plan_timing


def test_timing_aligns_to_next_boundary_with_lead_time():
    now = datetime(2026, 8, 18, 14, 31, 50, tzinfo=timezone.utc)
    timing = plan_timing(
        now=now,
        expiry_seconds=300,
        alignment_seconds=60,
        entry_window_seconds=3,
        minimum_lead_seconds=15,
    )

    assert timing.entry_at == datetime(2026, 8, 18, 14, 33, 0, tzinfo=timezone.utc)
    assert timing.entry_window_start == datetime(2026, 8, 18, 14, 32, 57, tzinfo=timezone.utc)
    assert timing.entry_window_end == datetime(2026, 8, 18, 14, 33, 3, tzinfo=timezone.utc)
    assert timing.expiry_at == datetime(2026, 8, 18, 14, 38, 0, tzinfo=timezone.utc)


def test_timing_uses_next_boundary_when_lead_is_sufficient():
    now = datetime(2026, 8, 18, 14, 31, 20, tzinfo=timezone.utc)
    timing = plan_timing(
        now=now,
        expiry_seconds=300,
        alignment_seconds=60,
        entry_window_seconds=3,
        minimum_lead_seconds=15,
    )

    assert timing.entry_at == datetime(2026, 8, 18, 14, 32, 0, tzinfo=timezone.utc)
    assert timing.expiry_at == datetime(2026, 8, 18, 14, 37, 0, tzinfo=timezone.utc)
