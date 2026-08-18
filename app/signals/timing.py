from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class SignalTiming:
    created_at: datetime
    entry_at: datetime
    entry_window_start: datetime
    entry_window_end: datetime
    expiry_at: datetime


def plan_timing(
    *,
    now: datetime | None = None,
    expiry_seconds: int,
    alignment_seconds: int = 60,
    entry_window_seconds: int = 3,
    minimum_lead_seconds: int = 15,
) -> SignalTiming:
    if expiry_seconds <= 0:
        raise ValueError('expiry_seconds must be positive')
    if alignment_seconds <= 0:
        raise ValueError('alignment_seconds must be positive')
    if entry_window_seconds < 0:
        raise ValueError('entry_window_seconds cannot be negative')
    if minimum_lead_seconds < 0:
        raise ValueError('minimum_lead_seconds cannot be negative')

    created_at = now or datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    else:
        created_at = created_at.astimezone(timezone.utc)

    epoch = int(created_at.timestamp())
    next_boundary = ((epoch // alignment_seconds) + 1) * alignment_seconds
    entry_at = datetime.fromtimestamp(next_boundary, tz=timezone.utc)

    if (entry_at - created_at).total_seconds() < minimum_lead_seconds:
        entry_at += timedelta(seconds=alignment_seconds)

    delta = timedelta(seconds=entry_window_seconds)
    expiry_at = entry_at + timedelta(seconds=expiry_seconds)

    return SignalTiming(
        created_at=created_at,
        entry_at=entry_at,
        entry_window_start=entry_at - delta,
        entry_window_end=entry_at + delta,
        expiry_at=expiry_at,
    )
