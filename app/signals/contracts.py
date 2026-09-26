from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


class ScanStage(str, enum.Enum):
    """Lifecycle scanning stages anchored to BC.Game round timing."""
    STAGE_A_PREPARING = 'STAGE_A_PREPARING'
    STAGE_B_FINAL = 'STAGE_B_FINAL'
    POST_CUTOFF = 'POST_CUTOFF'
    UNALIGNED = 'UNALIGNED'


@dataclass(frozen=True)
class PredictionTarget:
    """Explicit temporal prediction target: [priceStartTime, priceEndTime]."""
    round_id: str
    target_start: datetime
    target_end: datetime
    lead_time_seconds: float
    duration_seconds: float
    scan_time: datetime
    trade_cutoff: datetime | None = None
    seconds_until_cutoff: float | None = None

    @property
    def is_five_second_contract(self) -> bool:
        return 4.5 <= self.duration_seconds <= 5.5

    @property
    def is_authoritative_post_cutoff(self) -> bool:
        """Determines whether the authoritative BC.Game trade cutoff has actually elapsed."""
        if self.seconds_until_cutoff is not None:
            return self.seconds_until_cutoff <= 0.0
        return self.lead_time_seconds <= 0.0

    @property
    def scan_stage(self) -> ScanStage:
        if self.is_authoritative_post_cutoff:
            return ScanStage.POST_CUTOFF
        elif self.lead_time_seconds > 10.0:
            return ScanStage.STAGE_A_PREPARING
        else:
            return ScanStage.STAGE_B_FINAL

    def execution_authorized(self, min_dispatch_margin_seconds: float = 8.0) -> bool:
        """Separates prediction validity from trade dispatch/execution authorization.

        Even if a prediction for [T1, T2] is mathematically valid at e.g. 2s before T1,
        execution via user dispatch requires a safe latency margin to ensure transaction
        arrival before the trade cutoff.
        """
        remaining = self.seconds_until_cutoff if self.seconds_until_cutoff is not None else self.lead_time_seconds
        return remaining >= min_dispatch_margin_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            'round_id': self.round_id,
            'target_start': self.target_start.isoformat(),
            'target_end': self.target_end.isoformat(),
            'trade_cutoff': self.trade_cutoff.isoformat() if self.trade_cutoff else None,
            'lead_time_seconds': round(self.lead_time_seconds, 3),
            'seconds_until_cutoff': round(self.seconds_until_cutoff, 3) if self.seconds_until_cutoff is not None else None,
            'duration_seconds': round(self.duration_seconds, 3),
            'scan_time': self.scan_time.isoformat(),
            'scan_stage': self.scan_stage.value,
            'is_five_second_contract': self.is_five_second_contract,
            'is_authoritative_post_cutoff': self.is_authoritative_post_cutoff,
        }


@dataclass(frozen=True)
class RoundPredictionContext:
    """Structured authoritative round context received from BCGameRoundService."""
    round_id: str
    current_server_time_ms: int
    price_start_time_ms: int
    price_end_time_ms: int
    trade_cutoff_time_ms: int | None
    seconds_until_start: float
    contract_duration_seconds: float
    status: int
    phase: str
    is_fresh: bool
    observed_at: datetime
    feed_age_ms: int = 0

    @property
    def authoritative_cutoff_ms(self) -> int:
        return self.trade_cutoff_time_ms or self.price_start_time_ms

    @property
    def seconds_until_cutoff(self) -> float:
        if self.current_server_time_ms:
            return (self.authoritative_cutoff_ms - self.current_server_time_ms) / 1000.0
        return self.seconds_until_start

    @property
    def is_post_cutoff(self) -> bool:
        return self.seconds_until_cutoff <= 0.0 or self.seconds_until_start <= 0.0

    @property
    def can_predict(self) -> bool:
        return bool(
            self.is_fresh
            and self.status == 1001
            and self.round_id
            and 4.5 <= self.contract_duration_seconds <= 5.5
            and not self.is_post_cutoff
        )

    def to_target(self, scan_time: datetime | None = None) -> PredictionTarget:
        now = scan_time or datetime.now(timezone.utc)
        start_dt = datetime.fromtimestamp(self.price_start_time_ms / 1000.0, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(self.price_end_time_ms / 1000.0, tz=timezone.utc)
        cutoff_dt = datetime.fromtimestamp(self.authoritative_cutoff_ms / 1000.0, tz=timezone.utc)

        return PredictionTarget(
            round_id=self.round_id,
            target_start=start_dt,
            target_end=end_dt,
            lead_time_seconds=max(0.0, self.seconds_until_start),
            duration_seconds=self.contract_duration_seconds,
            scan_time=now,
            trade_cutoff=cutoff_dt,
            seconds_until_cutoff=self.seconds_until_cutoff,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'round_id': self.round_id,
            'current_server_time_ms': self.current_server_time_ms,
            'price_start_time_ms': self.price_start_time_ms,
            'price_end_time_ms': self.price_end_time_ms,
            'trade_cutoff_time_ms': self.trade_cutoff_time_ms,
            'seconds_until_start': round(self.seconds_until_start, 3),
            'seconds_until_cutoff': round(self.seconds_until_cutoff, 3),
            'contract_duration_seconds': round(self.contract_duration_seconds, 3),
            'status': self.status,
            'phase': self.phase,
            'is_fresh': self.is_fresh,
            'feed_age_ms': self.feed_age_ms,
            'observed_at': self.observed_at.isoformat(),
            'can_predict': self.can_predict,
            'is_post_cutoff': self.is_post_cutoff,
        }
