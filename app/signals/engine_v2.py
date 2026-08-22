from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.entities import SignalDirection
from app.services.cross_venue_microstructure import CrossVenueSnapshot
from app.signals.decision import SignalDecision
from app.signals.features import FeatureSnapshot


def _clamp(value: float, low: float = -1.5, high: float = 1.5) -> float:
    return max(low, min(high, value))


def _signed_ratio(value: float | None, neutral: float = 0.5, scale: float = 0.12) -> float:
    if value is None:
        return 0.0
    return _clamp((value - neutral) / scale)


@dataclass(frozen=True)
class EngineV2Result:
    decision: SignalDecision
    details: dict[str, Any]


class BTCFiveSecondEngine:
    """Unified BTC/USD five-second directional engine.

    The previous strategy applied several independent gates after scoring. That
    made the same evidence get judged multiple times and could turn a reasonable
    setup into NO_TRADE late in the pipeline. This engine combines every input
    exactly once into one signed directional edge.

    Positive edge = UP, negative edge = DOWN. NO_TRADE is reserved for genuinely
    weak/ambiguous evidence or clearly unsafe timing/data conditions.
    """

    def evaluate(
        self,
        features: FeatureSnapshot,
        cross: CrossVenueSnapshot,
        *,
        seconds_until_start: float | None,
        contract_duration_seconds: float | None,
    ) -> EngineV2Result:
        if contract_duration_seconds is not None and not 4.5 <= contract_duration_seconds <= 5.5:
            decision = SignalDecision(
                direction=SignalDirection.NO_TRADE,
                quality='NO_TRADE',
                bull_score=0,
                bear_score=0,
                margin=0,
                reason='BCGAME contract timing does not match the five-second prediction model.',
            )
            return EngineV2Result(decision, {'hard_reject': 'contract_duration'})

        # The further BCGAME Start Rate is from now, the less useful a single
        # one-second impulse becomes. Persistent 3s/5s movement gets more weight.
        horizon = max(0.0, seconds_until_start or 0.0)
        if horizon >= 10.0:
            w1, w3, w5 = 0.08, 0.32, 0.60
        elif horizon >= 7.0:
            w1, w3, w5 = 0.14, 0.36, 0.50
        else:
            w1, w3, w5 = 0.22, 0.38, 0.40

        n1 = _clamp(features.tick_return_1s_pct / 0.004)
        n3 = _clamp(features.tick_return_3s_pct / 0.008)
        n5 = _clamp(features.tick_return_5s_pct / 0.012)
        momentum = (n1 * w1) + (n3 * w3) + (n5 * w5)

        # Aggressor flow is useful evidence, but no longer a mandatory 60/40
        # gate. A 56/44 market can still qualify when independent evidence agrees.
        flow = _signed_ratio(features.trade_buy_ratio)

        # Acceleration rewards a move that is strengthening and penalizes one
        # that is already fading into the BCGAME start window.
        acceleration = _clamp(features.tick_acceleration_pct / 0.004)

        # Cross-venue book pressure is continuous rather than UP/DOWN/MIXED-only.
        # This keeps useful partial agreement instead of throwing it away.
        book_parts: list[float] = []
        if cross.fresh:
            for venue in (cross.binance, cross.bybit):
                if venue is None:
                    continue
                imbalance = _clamp(venue.imbalance / 0.15)
                microprice = _clamp(venue.microprice_bias_bps / 0.03)
                book_parts.append((imbalance * 0.70) + (microprice * 0.30))
        book = sum(book_parts) / len(book_parts) if book_parts else 0.0

        # Slow candle context is deliberately small. It can support a five-second
        # call but cannot overpower live microstructure.
        context = 0.0
        if features.ema_fast > features.ema_slow:
            context += 0.5
        elif features.ema_fast < features.ema_slow:
            context -= 0.5
        if features.structure == 'BULLISH':
            context += 0.5
        elif features.structure == 'BEARISH':
            context -= 0.5

        edge = (
            (momentum * 0.48)
            + (flow * 0.17)
            + (book * 0.25)
            + (acceleration * 0.06)
            + (context * 0.04)
        )

        # Reversal penalty: do not hard-cap the score. Reduce confidence only when
        # the newest impulse is meaningfully opposing the persistent move.
        reversal_penalty = 0.0
        if features.tick_return_3s_pct > 0.006 and features.tick_return_1s_pct < -0.004:
            reversal_penalty = min(0.22, abs(features.tick_return_1s_pct) / 0.04)
            edge -= reversal_penalty
        elif features.tick_return_3s_pct < -0.006 and features.tick_return_1s_pct > 0.004:
            reversal_penalty = min(0.22, abs(features.tick_return_1s_pct) / 0.04)
            edge += reversal_penalty

        # Noise raises the required edge instead of automatically rejecting both
        # directions. Only exceptional micro-volatility is treated as unsafe.
        volatility = features.tick_volatility_5s_pct
        threshold = 0.30
        if horizon >= 10.0:
            threshold += 0.08
        elif horizon >= 7.0:
            threshold += 0.04
        if not cross.fresh:
            threshold += 0.08
        if cross.fresh and not cross.healthy_spread:
            threshold += 0.08
        if volatility > 0.020:
            threshold += min(0.12, (volatility - 0.020) * 4.0)

        hard_noise = volatility > 0.060
        magnitude = abs(edge)
        if hard_noise or magnitude < threshold:
            reason = (
                'BTC micro-volatility is exceptionally high.'
                if hard_noise
                else 'Directional evidence is currently too balanced.'
            )
            decision = SignalDecision(
                direction=SignalDirection.NO_TRADE,
                quality='NO_TRADE',
                bull_score=max(0, round(max(edge, 0.0) * 10)),
                bear_score=max(0, round(max(-edge, 0.0) * 10)),
                margin=round(magnitude * 10),
                reason=reason,
            )
        else:
            direction = SignalDirection.UP if edge > 0 else SignalDirection.DOWN
            quality = 'STRONG' if magnitude >= threshold + 0.24 else 'VALID'
            directional_score = max(1, round(magnitude * 10))
            decision = SignalDecision(
                direction=direction,
                quality=quality,
                bull_score=directional_score if direction == SignalDirection.UP else 0,
                bear_score=directional_score if direction == SignalDirection.DOWN else 0,
                margin=directional_score,
                reason=(
                    f'Unified edge {edge:+.3f}; required {threshold:.3f}. '
                    'Momentum, trade flow, cross-venue books, timing and context were evaluated together.'
                ),
            )

        details = {
            'engine': 'BTC_5S_UNIFIED_V2',
            'edge': round(edge, 5),
            'threshold': round(threshold, 5),
            'momentum': round(momentum, 5),
            'trade_flow': round(flow, 5),
            'orderbook': round(book, 5),
            'acceleration': round(acceleration, 5),
            'context': round(context, 5),
            'volatility_5s_pct': round(volatility, 6),
            'reversal_penalty': round(reversal_penalty, 5),
            'seconds_until_start': seconds_until_start,
            'contract_duration_seconds': contract_duration_seconds,
            'cross_fresh': cross.fresh,
            'cross_consensus': cross.consensus,
            'healthy_spread': cross.healthy_spread,
        }
        return EngineV2Result(decision, details)


btc_five_second_engine = BTCFiveSecondEngine()
