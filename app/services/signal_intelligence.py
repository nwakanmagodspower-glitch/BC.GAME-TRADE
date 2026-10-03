from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import time
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.models.entities import SignalDirection
from app.services.market_data import MarketSnapshot, market_data_service
from app.services.microstructure_intelligence import microstructure_intelligence_service
from app.signals.contracts import PredictionTarget, RoundPredictionContext, ScanStage
from app.signals.decision import SignalDecision, decide
from app.signals.features import FeatureSnapshot, build_features
from app.signals.microstructure.decision import MicrostructureDecision
from app.signals.microstructure.features import MicrostructureFeatureSnapshot
from app.signals.scoring import score_features

settings = get_settings()

ENGINE_NAME = settings.strategy_version


@dataclass(frozen=True)
class IntelligenceResult:
    market: str
    direction: SignalDirection
    quality: str
    reference_price: float | None
    market_snapshot: MarketSnapshot | None
    features: FeatureSnapshot | MicrostructureFeatureSnapshot | None
    decision: SignalDecision | MicrostructureDecision | None
    reason: str
    service_available: bool = True
    seconds_until_start: float | None = None
    contract_duration_seconds: float | None = None
    engine_details: dict[str, Any] | None = None
    target: PredictionTarget | None = None
    context: RoundPredictionContext | None = None
    scan_stage: str = 'UNALIGNED'
    temporal_alignment_valid: bool = False


class SignalIntelligenceService:
    """BTC intelligence engine anchored to the authoritative BC.Game contract window [T1, T2].

    The prediction target is specifically the BTC movement during the upcoming contract window:
    [priceStartTime, priceEndTime]. Movement during the pre-start lead gap [NOW, T1] is evaluated
    for impulse persistence vs exhaustion, rather than being confused with the contract target.
    """

    def __init__(self) -> None:
        self._scan_lock = asyncio.Lock()
        self._last_result: IntelligenceResult | None = None
        self._last_result_at: float = 0.0
        self._last_compute_duration_ms: int | None = None
        self._compute_count = 0
        self._cache_hit_count = 0

    def operational_status(self) -> dict[str, Any]:
        """Return non-secret engine readiness and latency diagnostics."""
        age_ms = None
        if self._last_result is not None:
            age_ms = max(0, int((time.monotonic() - self._last_result_at) * 1000))
        return {
            'engine': ENGINE_NAME,
            'has_completed_scan': self._last_result is not None,
            'last_scan_available': (
                self._last_result.service_available if self._last_result is not None else None
            ),
            'last_compute_duration_ms': self._last_compute_duration_ms,
            'last_result_age_ms': age_ms,
            'compute_count': self._compute_count,
            'coalesced_cache_hits': self._cache_hit_count,
        }

    async def scan(
        self,
        symbol: str | None = None,
        *,
        round_context: RoundPredictionContext | None = None,
        target: PredictionTarget | None = None,
        seconds_until_start: float | None = None,
        contract_duration_seconds: float | None = None,
    ) -> IntelligenceResult:
        market = (symbol or settings.analysis_pair).upper()
        if market != settings.analysis_pair.upper():
            return IntelligenceResult(
                market=market,
                direction=SignalDirection.NO_TRADE,
                quality='UNAVAILABLE',
                reference_price=None,
                market_snapshot=None,
                features=None,
                decision=None,
                reason=f'Unsupported market: {market}.',
                service_available=False,
                seconds_until_start=seconds_until_start,
                contract_duration_seconds=contract_duration_seconds,
                target=target,
                context=round_context,
            )

        resolved_target: PredictionTarget | None = target
        temporal_alignment_valid = False

        if round_context is not None:
            # Authoritative BC.Game observer clock validation
            if not round_context.is_fresh:
                return IntelligenceResult(
                    market=market,
                    direction=SignalDirection.NO_TRADE,
                    quality='STALE_OBSERVATION',
                    reference_price=None,
                    market_snapshot=None,
                    features=None,
                    decision=None,
                    reason='Authoritative BC.Game round observation is stale. Waiting for fresh clock sync.',
                    service_available=True,
                    seconds_until_start=round_context.seconds_until_start,
                    contract_duration_seconds=round_context.contract_duration_seconds,
                    target=round_context.to_target(),
                    context=round_context,
                    scan_stage=ScanStage.UNALIGNED.value,
                    temporal_alignment_valid=False,
                )

            if round_context.status != 1001 or round_context.phase != 'BETTING':
                return IntelligenceResult(
                    market=market,
                    direction=SignalDirection.NO_TRADE,
                    quality='UNAVAILABLE',
                    reference_price=None,
                    market_snapshot=None,
                    features=None,
                    decision=None,
                    reason=f'⏱️ BC.Game round {round_context.round_id} is not open for betting ({round_context.phase}).',
                    service_available=True,
                    seconds_until_start=round_context.seconds_until_start,
                    contract_duration_seconds=round_context.contract_duration_seconds,
                    target=round_context.to_target(),
                    context=round_context,
                    scan_stage=round_context.to_target().scan_stage.value,
                    temporal_alignment_valid=False,
                )

            if not (4.5 <= round_context.contract_duration_seconds <= 5.5):
                return IntelligenceResult(
                    market=market,
                    direction=SignalDirection.NO_TRADE,
                    quality='INVALID_CONTRACT',
                    reference_price=None,
                    market_snapshot=None,
                    features=None,
                    decision=None,
                    reason=f'Contract duration ({round_context.contract_duration_seconds:.1f}s) is not the expected 5-second window.',
                    service_available=True,
                    seconds_until_start=round_context.seconds_until_start,
                    contract_duration_seconds=round_context.contract_duration_seconds,
                    target=round_context.to_target(),
                    context=round_context,
                    scan_stage=ScanStage.UNALIGNED.value,
                    temporal_alignment_valid=False,
                )

            if round_context.is_post_cutoff:
                return IntelligenceResult(
                    market=market,
                    direction=SignalDirection.NO_TRADE,
                    quality='POST_CUTOFF',
                    reference_price=None,
                    market_snapshot=None,
                    features=None,
                    decision=None,
                    reason=f'Authoritative trade cutoff for round {round_context.round_id} has elapsed.',
                    service_available=True,
                    seconds_until_start=0.0,
                    contract_duration_seconds=round_context.contract_duration_seconds,
                    target=round_context.to_target(),
                    context=round_context,
                    scan_stage=ScanStage.POST_CUTOFF.value,
                    temporal_alignment_valid=False,
                )

            resolved_target = round_context.to_target()
            temporal_alignment_valid = True
            seconds_until_start = round_context.seconds_until_start
            contract_duration_seconds = round_context.contract_duration_seconds

        elif target is not None:
            if not target.is_five_second_contract:
                return IntelligenceResult(
                    market=market,
                    direction=SignalDirection.NO_TRADE,
                    quality='INVALID_CONTRACT',
                    reference_price=None,
                    market_snapshot=None,
                    features=None,
                    decision=None,
                    reason=f'Target duration ({target.duration_seconds:.1f}s) is not the expected 5-second window.',
                    service_available=True,
                    target=target,
                    scan_stage=target.scan_stage.value,
                    temporal_alignment_valid=False,
                )
            if target.is_authoritative_post_cutoff:
                return IntelligenceResult(
                    market=market,
                    direction=SignalDirection.NO_TRADE,
                    quality='POST_CUTOFF',
                    reference_price=None,
                    market_snapshot=None,
                    features=None,
                    decision=None,
                    reason=f'Authoritative trade cutoff for round {target.round_id} has elapsed.',
                    service_available=True,
                    target=target,
                    scan_stage=ScanStage.POST_CUTOFF.value,
                    temporal_alignment_valid=False,
                )
            temporal_alignment_valid = True
            seconds_until_start = target.lead_time_seconds
            contract_duration_seconds = target.duration_seconds

        target_round_id = resolved_target.round_id if resolved_target else None
        max_cache_age = max(0.0, settings.signal_scan_coalesce_ms / 1000.0)
        now_mono = time.monotonic()

        # Cache check with strict Round Identity enforcement
        if self._cached_result_is_usable(now_mono, max_cache_age, target_round_id=target_round_id):
            assert self._last_result is not None
            self._cache_hit_count += 1
            return self._with_timer(
                self._last_result,
                seconds_until_start,
                contract_duration_seconds,
                target=resolved_target,
                context=round_context,
            )

        async with self._scan_lock:
            now_mono = time.monotonic()
            if self._cached_result_is_usable(now_mono, max_cache_age, target_round_id=target_round_id):
                assert self._last_result is not None
                self._cache_hit_count += 1
                return self._with_timer(
                    self._last_result,
                    seconds_until_start,
                    contract_duration_seconds,
                    target=resolved_target,
                    context=round_context,
                )

            compute_started = time.monotonic()
            result = await self._compute(
                market,
                target=resolved_target,
                context=round_context,
                temporal_alignment_valid=temporal_alignment_valid,
            )
            self._last_compute_duration_ms = max(
                0, int((time.monotonic() - compute_started) * 1000)
            )
            self._compute_count += 1
            self._last_result = result
            self._last_result_at = time.monotonic()
            return self._with_timer(
                result,
                seconds_until_start,
                contract_duration_seconds,
                target=resolved_target,
                context=round_context,
            )

    def _cached_result_is_usable(
        self,
        now_mono: float,
        max_cache_age: float,
        target_round_id: str | None = None,
    ) -> bool:
        result = self._last_result
        if result is None or (now_mono - self._last_result_at) > max_cache_age:
            return False

        # Fail closed on round mismatch: never execute or reuse a prediction from a different round
        if target_round_id is not None:
            if result.target is None or result.target.round_id != target_round_id:
                return False

        snapshot = result.market_snapshot
        if snapshot is None:
            return True
        age = time.time() - snapshot.event_time.timestamp()
        return -settings.market_data_future_skew_seconds <= age <= settings.market_data_max_age_seconds

    @staticmethod
    def _with_timer(
        result: IntelligenceResult,
        seconds_until_start: float | None,
        contract_duration_seconds: float | None,
        *,
        target: PredictionTarget | None = None,
        context: RoundPredictionContext | None = None,
    ) -> IntelligenceResult:
        timer_validated = (
            contract_duration_seconds is None
            or 4.5 <= contract_duration_seconds <= 5.5
        )
        resolved_target = target or result.target
        resolved_context = context or result.context
        stage = (
            resolved_target.scan_stage.value
            if resolved_target
            else result.scan_stage
        )
        details = dict(result.engine_details or {})
        details.update(
            {
                'timer_validated': timer_validated,
                'seconds_until_start': seconds_until_start,
                'contract_duration_seconds': contract_duration_seconds,
                'round_id': resolved_target.round_id if resolved_target else None,
                'target_start': resolved_target.target_start.isoformat() if resolved_target else None,
                'target_end': resolved_target.target_end.isoformat() if resolved_target else None,
                'scan_stage': stage,
            }
        )
        return IntelligenceResult(
            market=result.market,
            direction=result.direction,
            quality=result.quality,
            reference_price=result.reference_price,
            market_snapshot=result.market_snapshot,
            features=result.features,
            decision=result.decision,
            reason=result.reason,
            service_available=result.service_available,
            seconds_until_start=seconds_until_start,
            contract_duration_seconds=contract_duration_seconds,
            engine_details=details,
            target=resolved_target,
            context=resolved_context,
            scan_stage=stage,
            temporal_alignment_valid=bool(resolved_target and timer_validated),
        )

    async def _compute(
        self,
        market: str,
        *,
        target: PredictionTarget | None = None,
        context: RoundPredictionContext | None = None,
        temporal_alignment_valid: bool = False,
    ) -> IntelligenceResult:
        snapshot = None
        if settings.detrade_use_synthetic_feed:
            try:
                from app.integrations.detrade_observer import detrade_observer
                if detrade_observer.latest_tick and detrade_observer.latest_tick.get('price'):
                    now_mono = time.monotonic()
                    age = now_mono - float(detrade_observer.latest_tick.get('received_monotonic', 0))
                    if 0 <= age <= settings.market_data_max_age_seconds:
                        p = float(detrade_observer.latest_tick['price'])
                        snapshot = MarketSnapshot(
                            symbol=market,
                            price=p,
                            event_time=detrade_observer.latest_tick.get('received_at', datetime.now(timezone.utc)),
                            source='DETRADE_SYNTHETIC',
                            fresh=True,
                        )
            except Exception:
                pass

        if snapshot is None:
            snapshot = await market_data_service.cache.get_snapshot(
                market,
                max_age_seconds=settings.market_data_max_age_seconds,
            )

        if snapshot is None:
            return IntelligenceResult(
                market=market,
                direction=SignalDirection.NO_TRADE,
                quality='UNAVAILABLE',
                reference_price=None,
                market_snapshot=None,
                features=None,
                decision=None,
                reason='Live BTC price stream has not warmed up yet.',
                service_available=False,
                target=target,
                context=context,
            )
        if not snapshot.fresh:
            return IntelligenceResult(
                market=market,
                direction=SignalDirection.NO_TRADE,
                quality='UNAVAILABLE',
                reference_price=snapshot.price,
                market_snapshot=snapshot,
                features=None,
                decision=None,
                reason='Live BTC price stream is stale.',
                service_available=False,
                target=target,
                context=context,
            )

        scan_stage = target.scan_stage.value if target else ScanStage.UNALIGNED.value

        # Check target cutoff veto first
        if target and target.scan_stage == ScanStage.POST_CUTOFF:
            return IntelligenceResult(
                market=market,
                direction=SignalDirection.NO_TRADE,
                quality='NO_TRADE',
                reference_price=snapshot.price,
                market_snapshot=snapshot,
                features=None,
                decision=SignalDecision(
                    direction=SignalDirection.NO_TRADE,
                    quality='NO_TRADE',
                    bull_score=0,
                    bear_score=0,
                    margin=0,
                    reason='Order placement cutoff has passed.',
                ),
                reason='Order placement cutoff has passed.',
                service_available=True,
                target=target,
                context=context,
                scan_stage=scan_stage,
                temporal_alignment_valid=temporal_alignment_valid,
                engine_details={
                    'engine': ENGINE_NAME,
                    'scan_stage': scan_stage,
                    'round_id': target.round_id,
                },
            )

        # 1. Primary Engine: 5-Second Microstructure Intelligence Engine
        try:
            ms_result = await microstructure_intelligence_service.scan(
                market,
                seconds_until_start=seconds_until_start,
                contract_duration_seconds=contract_duration_seconds,
                now=now_dt,
                round_context=context,
            )
            if ms_result.service_available and ms_result.decision is not None and ms_result.features is not None:
                details = {
                    'engine': ms_result.engine,
                    'bull_score': ms_result.decision.bull_score,
                    'bear_score': ms_result.decision.bear_score,
                    'margin': ms_result.decision.margin,
                    'bar_5s_return': ms_result.features.bar_5s_return,
                    'bar_5s_range': ms_result.features.bar_5s_range,
                    'lead_range_dollars': ms_result.features.lead_range_dollars,
                    'bar_5s_taker_ratio': ms_result.features.bar_5s_taker_ratio,
                    'spread_bps': ms_result.features.spread_bps,
                    'obi_l5': ms_result.features.obi_l5,
                    'microprice_dev_bps': ms_result.features.microprice_dev_bps,
                    'internal_velocity_usd': ms_result.features.internal_velocity_usd,
                    'internal_acceleration_usd': ms_result.features.internal_acceleration_usd,
                    'station_nearest_barrier_dist': ms_result.features.station_nearest_barrier_dist,
                    'station_nearest_barrier_type': ms_result.features.station_nearest_barrier_type,
                    'station_travel_time_seconds': ms_result.features.station_travel_time_seconds,
                    'regime_classification': ms_result.features.regime_classification,
                    'round_progress_pct': ms_result.features.round_progress_pct,
                    'round_id': target.round_id if target else None,
                    'target_start': target.target_start.isoformat() if target else None,
                    'target_end': target.target_end.isoformat() if target else None,
                    'lead_time_seconds': target.lead_time_seconds if target else None,
                    'contract_duration_seconds': target.duration_seconds if target else None,
                    'scan_stage': scan_stage,
                    'temporal_alignment_valid': temporal_alignment_valid,
                }
                return IntelligenceResult(
                    market=market,
                    direction=ms_result.direction,
                    quality=ms_result.quality,
                    reference_price=ms_result.reference_price or snapshot.price,
                    market_snapshot=snapshot,
                    features=ms_result.features,
                    decision=ms_result.decision,
                    reason=ms_result.reason,
                    service_available=True,
                    engine_details=details,
                    target=target,
                    context=context,
                    scan_stage=scan_stage,
                    temporal_alignment_valid=temporal_alignment_valid,
                )
        except Exception:
            pass

        # 2. Fallback if microstructure stream is not yet active (e.g. unit tests without websocket ticks)
        candles = await market_data_service.get_cached_candles(market)
        if not candles:
            return IntelligenceResult(
                market=market,
                direction=SignalDirection.NO_TRADE,
                quality='UNAVAILABLE',
                reference_price=snapshot.price,
                market_snapshot=snapshot,
                features=None,
                decision=None,
                reason='BTC market data stream is warming up.',
                service_available=False,
                target=target,
                context=context,
            )

        ticks = await market_data_service.cache.get_recent_ticks(
            market,
            lookback_seconds=settings.signal_trade_flow_lookback_seconds,
        )

        try:
            features = build_features(candles, ticks, target=target)
        except Exception as exc:
            return IntelligenceResult(
                market=market,
                direction=SignalDirection.NO_TRADE,
                quality='UNAVAILABLE',
                reference_price=snapshot.price,
                market_snapshot=snapshot,
                features=None,
                decision=None,
                reason=f'BTC feature preparation failed ({type(exc).__name__}).',
                service_available=False,
                target=target,
                context=context,
            )

        score = score_features(features)
        decision = decide(
            score,
            min_score=settings.signal_min_score,
            min_margin=settings.signal_min_margin,
            target=target,
            features=features,
            min_lead_range=settings.signal_min_lead_range_dollars,
        )
        details = {
            'engine': ENGINE_NAME,
            'bull_score': decision.bull_score,
            'bear_score': decision.bear_score,
            'margin': decision.margin,
            'lead_range_dollars': features.lead_range_dollars,
            'lead_mom_dollars': features.lead_mom_dollars,
            'lead_speed_sec': features.lead_speed_sec,
            'round_id': target.round_id if target else None,
            'target_start': target.target_start.isoformat() if target else None,
            'target_end': target.target_end.isoformat() if target else None,
            'lead_time_seconds': target.lead_time_seconds if target else None,
            'contract_duration_seconds': target.duration_seconds if target else None,
            'scan_stage': scan_stage,
            'temporal_alignment_valid': temporal_alignment_valid,
        }

        return IntelligenceResult(
            market=market,
            direction=decision.direction,
            quality=decision.quality,
            reference_price=snapshot.price,
            market_snapshot=snapshot,
            features=features,
            decision=decision,
            reason=decision.reason,
            service_available=True,
            engine_details=details,
            target=target,
            context=context,
            scan_stage=scan_stage,
            temporal_alignment_valid=temporal_alignment_valid,
        )


signal_intelligence_service = SignalIntelligenceService()
