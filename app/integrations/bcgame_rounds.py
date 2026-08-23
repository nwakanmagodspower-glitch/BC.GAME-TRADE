from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.config import get_settings
from app.integrations.detrade_observer import DeTradeRoundObservation, detrade_observer

settings = get_settings()


@dataclass(frozen=True)
class BCGameRoundSnapshot:
    round_id: str
    observed_at: datetime
    order_closes_at: datetime
    start_rate_at: datetime
    end_rate_at: datetime
    stake_band: str
    source: str = 'AUTO_SYNC'
    deadline_monotonic: float | None = None
    up_payout_pct: float | None = None
    down_payout_pct: float | None = None
    up_pool_amount: float | None = None
    down_pool_amount: float | None = None
    up_players: int | None = None
    down_players: int | None = None

    def seconds_until_order_close(self, now: datetime) -> float:
        if self.deadline_monotonic is not None:
            return self.deadline_monotonic - time.monotonic()
        return (self.order_closes_at - now).total_seconds()


@dataclass(frozen=True)
class BCGameRoundDecision:
    synchronized: bool
    actionable: bool
    snapshot: BCGameRoundSnapshot | None
    reason: str
    phase: str | None = None
    status_code: int | None = None
    remaining_seconds: float | None = None
    feed_age_ms: int | None = None


@dataclass(frozen=True)
class BCGameRoundStatus:
    enabled: bool
    seen: bool
    fresh: bool
    age_seconds: float | None
    round_id: str | None
    last_error: str | None


class BCGameRoundService:
    """Single boundary for current BC.GAME/DeTrade round synchronization.

    MANUAL_SYNC and HYBRID fallback mean a user-triggered scan without a claimed
    authoritative round. This service creates round snapshots only from verified
    synchronized DeTrade observations; it never fabricates manual round IDs.
    """

    def __init__(self) -> None:
        self.last_error: str | None = None
        self.last_snapshot: BCGameRoundSnapshot | None = None
        self._probe_lock = asyncio.Lock()

    def status(self, now: datetime | None = None) -> BCGameRoundStatus:
        timing_mode = settings.signal_timing_mode.upper()
        if timing_mode == 'MANUAL_SYNC':
            return BCGameRoundStatus(
                True,
                True,
                True,
                0.0,
                'MANUAL_TRIGGER',
                'Manual Scan Now timing is active.',
            )
        if not settings.bcgame_round_sync_enabled:
            return BCGameRoundStatus(
                False,
                False,
                False,
                None,
                None,
                'Automatic BCGAME round synchronization is disabled.',
            )

        observation = detrade_observer.latest
        if observation is not None:
            return BCGameRoundStatus(
                True,
                True,
                bool(observation.fresh),
                max(0.0, observation.data_age_ms / 1000.0),
                observation.round_id,
                self.last_error,
            )

        snapshot = self.last_snapshot
        if snapshot is None:
            return BCGameRoundStatus(
                True,
                False,
                False,
                None,
                None,
                self.last_error or 'No synchronized BCGAME round has been observed yet.',
            )
        current = now or datetime.now(timezone.utc)
        observed = (
            snapshot.observed_at
            if snapshot.observed_at.tzinfo
            else snapshot.observed_at.replace(tzinfo=timezone.utc)
        )
        age = max(0.0, (current - observed.astimezone(timezone.utc)).total_seconds())
        fresh = age <= settings.bcgame_round_sync_max_age_seconds
        return BCGameRoundStatus(True, True, fresh, age, snapshot.round_id, self.last_error)

    async def _fresh_observation(self) -> DeTradeRoundObservation | None:
        latest = detrade_observer.latest
        if latest is not None and latest.data_age_ms <= settings.detrade_probe_coalesce_ms:
            return latest

        async with self._probe_lock:
            latest = detrade_observer.latest
            if latest is not None and latest.data_age_ms <= settings.detrade_probe_coalesce_ms:
                return latest
            return await detrade_observer.probe(
                timeout_seconds=settings.detrade_scan_probe_timeout_seconds
            )

    async def current_round_decision(self) -> BCGameRoundDecision:
        if not settings.bcgame_round_sync_enabled:
            self.last_error = 'Automatic BCGAME round synchronization is disabled.'
            return BCGameRoundDecision(False, False, None, self.last_error)
        if not settings.detrade_ws_enabled:
            self.last_error = 'DeTrade timing is not enabled.'
            return BCGameRoundDecision(False, False, None, self.last_error)

        observation = await self._fresh_observation()
        if observation is None:
            self.last_error = (
                detrade_observer.last_error
                or 'No authoritative DeTrade round frame was received.'
            )
            return BCGameRoundDecision(False, False, None, self.last_error)

        remaining_ms = observation.remaining_ms
        remaining_seconds = remaining_ms / 1000 if remaining_ms is not None else None
        decision_base = {
            'phase': observation.phase,
            'status_code': observation.status,
            'remaining_seconds': remaining_seconds,
            'feed_age_ms': observation.data_age_ms,
        }

        if (
            not observation.round_id
            or observation.price_start_time_ms is None
            or observation.price_end_time_ms is None
        ):
            self.last_error = 'The synchronized round frame is incomplete.'
            return BCGameRoundDecision(
                True, False, None, self.last_error, **decision_base
            )
        if not observation.fresh:
            self.last_error = (
                'The synchronized BCGAME round timer is stale. Wait for the next fresh round.'
            )
            return BCGameRoundDecision(
                True, False, None, self.last_error, **decision_base
            )
        if observation.status != 1001:
            self.last_error = (
                f'This BCGAME round is not accepting entries ({observation.phase}). '
                'Wait for the next round.'
            )
            return BCGameRoundDecision(
                True, False, None, self.last_error, **decision_base
            )
        if (
            remaining_ms is None
            or remaining_ms <= settings.detrade_latency_safety_margin_ms
        ):
            self.last_error = (
                'This BCGAME round is already too close to the cutoff. '
                'Wait for the next fresh round.'
            )
            return BCGameRoundDecision(
                True, False, None, self.last_error, **decision_base
            )

        evaluation_window_ms = (
            observation.price_end_time_ms - observation.price_start_time_ms
        )
        if not 4_500 <= evaluation_window_ms <= 5_500:
            self.last_error = (
                'The synchronized round does not match the configured 5-second contract.'
            )
            return BCGameRoundDecision(
                True, False, None, self.last_error, **decision_base
            )

        if observation.estimated_server_time_ms is None:
            self.last_error = 'The synchronized round does not contain usable server time.'
            return BCGameRoundDecision(
                True, False, None, self.last_error, **decision_base
            )

        observed_at = observation.received_at
        start_at = datetime.fromtimestamp(
            observation.price_start_time_ms / 1000,
            tz=timezone.utc,
        )
        end_at = datetime.fromtimestamp(
            observation.price_end_time_ms / 1000,
            tz=timezone.utc,
        )
        snapshot = BCGameRoundSnapshot(
            round_id=observation.round_id,
            observed_at=observed_at,
            order_closes_at=start_at,
            start_rate_at=start_at,
            end_rate_at=end_at,
            stake_band=settings.default_stake_band,
            source='DETRADE_SYNC',
            deadline_monotonic=observation.authoritative_deadline_monotonic,
        )
        self.last_snapshot = snapshot
        self.last_error = None
        return BCGameRoundDecision(
            True,
            True,
            snapshot,
            'Authoritative DeTrade round timing is active.',
            **decision_base,
        )

    async def current_actionable_round(self) -> BCGameRoundSnapshot | None:
        decision = await self.current_round_decision()
        return decision.snapshot if decision.actionable else None


bcgame_round_service = BCGameRoundService()
