from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.config import get_settings
from app.integrations.detrade_observer import DeTradeRoundObservation, detrade_observer
from app.signals.contracts import PredictionTarget, RoundPredictionContext

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
    current_server_time_ms: int | None = None
    status_code: int = 1001
    phase: str = 'BETTING'
    price_start_time_ms: int | None = None
    price_end_time_ms: int | None = None
    trade_cutoff_time_ms: int | None = None
    data_age_ms: int = 0

    def seconds_until_order_close(self, now: datetime) -> float:
        if self.deadline_monotonic is not None:
            return self.deadline_monotonic - time.monotonic()
        return (self.order_closes_at - now).total_seconds()

    def prediction_context(self, now: datetime | None = None) -> RoundPredictionContext:
        current_dt = now or datetime.now(timezone.utc)
        seconds_until_start = max(0.0, self.seconds_until_order_close(current_dt))
        duration_s = max(0.0, (self.end_rate_at - self.start_rate_at).total_seconds())
        start_ms = self.price_start_time_ms or int(self.start_rate_at.timestamp() * 1000)
        end_ms = self.price_end_time_ms or int(self.end_rate_at.timestamp() * 1000)
        server_ms = self.current_server_time_ms or int(current_dt.timestamp() * 1000)
        return RoundPredictionContext(
            round_id=self.round_id,
            current_server_time_ms=server_ms,
            price_start_time_ms=start_ms,
            price_end_time_ms=end_ms,
            trade_cutoff_time_ms=self.trade_cutoff_time_ms,
            seconds_until_start=seconds_until_start,
            contract_duration_seconds=duration_s,
            status=self.status_code,
            phase=self.phase,
            is_fresh=self.data_age_ms < settings.detrade_stale_after_ms,
            observed_at=self.observed_at,
            feed_age_ms=self.data_age_ms,
        )

    def prediction_target(self, now: datetime | None = None) -> PredictionTarget:
        return self.prediction_context(now).to_target(now)


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
    context: RoundPredictionContext | None = None
    target: PredictionTarget | None = None


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
        round_context = None
        prediction_target = None
        if (
            observation.round_id
            and observation.price_start_time_ms is not None
            and observation.price_end_time_ms is not None
        ):
            duration_s = max(
                0.0,
                (observation.price_end_time_ms - observation.price_start_time_ms) / 1000.0,
            )
            server_time_ms = observation.estimated_server_time_ms or observation.current_time_ms or 0
            secs_until_start = (remaining_ms / 1000.0) if remaining_ms is not None else 0.0
            round_context = RoundPredictionContext(
                round_id=observation.round_id,
                current_server_time_ms=server_time_ms,
                price_start_time_ms=observation.price_start_time_ms,
                price_end_time_ms=observation.price_end_time_ms,
                trade_cutoff_time_ms=observation.trade_cutoff_time_ms,
                seconds_until_start=secs_until_start,
                contract_duration_seconds=duration_s,
                status=observation.status or 0,
                phase=observation.phase,
                is_fresh=observation.fresh,
                observed_at=observation.received_at,
                feed_age_ms=observation.data_age_ms,
            )
            prediction_target = round_context.to_target()

        decision_base = {
            'phase': observation.phase,
            'status_code': observation.status,
            'remaining_seconds': remaining_seconds,
            'feed_age_ms': observation.data_age_ms,
            'context': round_context,
            'target': prediction_target,
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
            phase_detail = {
                'TRADE_CUTOFF': 'order window closed',
                'PAY_OUT': 'round settling payout',
                'FINISHED': 'round settled',
                'START_PAY_OUT': 'round settling',
                'READY_TO_START': 'round preparing to start',
            }.get(observation.phase, observation.phase)
            self.last_error = (
                f'⏱️ This BCGAME round is not accepting entries ({phase_detail}). '
                'Wait for the fresh round countdown on BC.GAME, then tap Scan.'
            )
            return BCGameRoundDecision(
                True, False, None, self.last_error, **decision_base
            )
        if (
            remaining_ms is None
            or remaining_ms <= settings.detrade_latency_safety_margin_ms
        ):
            self.last_error = (
                '⏱️ This BCGAME round is already too close to the cutoff (<10s remaining). '
                'Wait for the next fresh round to ensure safe entry.'
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
            current_server_time_ms=observation.estimated_server_time_ms,
            status_code=observation.status or 1001,
            phase=observation.phase,
            price_start_time_ms=observation.price_start_time_ms,
            price_end_time_ms=observation.price_end_time_ms,
            trade_cutoff_time_ms=observation.trade_cutoff_time_ms,
            data_age_ms=observation.data_age_ms,
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
