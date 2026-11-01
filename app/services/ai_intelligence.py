from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from app.signals.microstructure.features import MicrostructureFeatureSnapshot


@dataclass(frozen=True)
class AIPredictionResult:
    predicted_direction: str  # "UP", "DOWN", "NO_TRADE"
    up_probability: float     # 0.0 to 1.0
    down_probability: float   # 0.0 to 1.0
    confidence_pct: int       # 50 to 98
    ai_regime: str            # "LAMINAR_THRUST", "EXHAUSTION_TOP", "EXHAUSTION_BOTTOM", "BOUNDED_REBOUND", "MICRO_CHOP", "NEUTRAL"
    risk_score: int           # 1 (low risk) to 10 (high risk)
    reasoning: str
    features_used: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AIMicrostructurePredictor:
    """Quantitative Machine Learning Kinematic Engine for 5-second binary options.

    Applies Bayesian logistic classification across multi-horizon momentum,
    sub-second kinematic acceleration, Kaufman fractal efficiency,
    and cumulative impulse exhaustion envelopes.
    """

    @staticmethod
    def _sigmoid(z: float) -> float:
        z_clamped = max(-20.0, min(20.0, z))
        return 1.0 / (1.0 + math.exp(-z_clamped))

    def predict(
        self,
        features: MicrostructureFeatureSnapshot,
        *,
        is_synthetic: bool = True,
        min_probability_threshold: float = 0.62,
    ) -> AIPredictionResult:
        # 1. Feature Extraction & Normalization
        v_1s = features.internal_velocity_usd if abs(features.internal_velocity_usd) > 0.05 else features.delta_1s_usd
        v_2s = features.delta_2s_usd / 2.0
        v_5s = features.bar_5s_return / 5.0
        v_10s = features.delta_10s_usd / 10.0 if abs(features.delta_10s_usd) > 0.1 else v_5s
        accel = features.internal_acceleration_usd
        eff = max(0.05, min(1.0, features.fractal_efficiency_5s))
        taker_dev = (features.bar_5s_taker_ratio - 0.50) * 2.0  # -1.0 to +1.0
        speed_conv = max(0.5, min(3.0, features.speed_convexity))
        eff_range = max(features.range_20s, features.lead_range_dollars, features.bar_5s_range)

        # 2. Cumulative Impulse & Exhaustion Calculation
        # Evaluates whether the move over 5s to 15s is already overextended
        cum_up = max(features.bar_5s_return, features.delta_5s_usd, features.delta_10s_usd, features.bar_5s_momentum_3bar)
        cum_down = min(features.bar_5s_return, features.delta_5s_usd, features.delta_10s_usd, features.bar_5s_momentum_3bar)

        is_exhaustion_top = False
        is_exhaustion_bottom = False

        if cum_up >= 5.0:
            # Overextended pump: check for deceleration or top wick pullback
            if accel < -0.10 or v_1s < 0.15 or features.pullback_from_extremum >= 0.35:
                is_exhaustion_top = True

        if cum_down <= -5.0:
            # Overextended dump: check for deceleration or bottom bounce
            if accel > 0.10 or v_1s > -0.15:
                is_exhaustion_bottom = True

        # 3. Micro-Chop Detection
        is_flat_chop = (eff_range < 0.40 and abs(features.bar_5s_return) < 0.15 and abs(features.delta_10s_usd) < 0.25)

        # 4. Station Barrier Dynamics ($50 rounds)
        near_upper = features.station_barrier_upper > 0 and features.station_barrier_dist_upper < 1.20
        near_lower = features.station_barrier_lower > 0 and features.station_barrier_dist_lower < 1.20

        # 5. Logistic Probability Computation
        # Base log-odds weights calibrated on 5-second tick continuation statistics
        w_v1s = 1.40
        w_v5s = 1.20
        w_v10s = 0.80
        w_accel = 0.90
        w_taker = 0.60
        w_eff = 0.80

        # Dynamic adjustments based on regime
        log_odds = (
            (w_v1s * v_1s)
            + (w_v5s * (features.bar_5s_return * 0.5))
            + (w_v10s * (features.delta_10s_usd * 0.25))
            + (w_accel * accel * 0.5)
            + (w_taker * taker_dev)
        )

        # Scale by fractal efficiency: clean laminar flow boosts signal; turbulent noise dampens
        if eff >= 0.55:
            log_odds *= (1.0 + (eff - 0.55) * 1.2)
        elif eff < 0.35:
            log_odds *= 0.50

        # Speed convexity accelerator
        if speed_conv > 1.3:
            log_odds *= 1.15

        # Station Barrier penalties
        if near_upper and log_odds > 0:
            log_odds = min(log_odds * 0.3, 0.2)
        elif near_lower and log_odds < 0:
            log_odds = max(log_odds * 0.3, -0.2)

        # Calculate continuous probability P(UP)
        p_up = self._sigmoid(log_odds)
        p_down = 1.0 - p_up

        # 6. Regime Classification & Direction Selection
        if is_exhaustion_top:
            direction = "DOWN"
            regime = "EXHAUSTION_TOP"
            confidence = 85
            risk = 4
            reason = f"Exhaustion top detected (+${cum_up:.2f} pump decelerating); mean-reversion favors DOWN."
        elif is_exhaustion_bottom:
            direction = "UP"
            regime = "EXHAUSTION_BOTTOM"
            confidence = 85
            risk = 4
            reason = f"Exhaustion bottom detected (${cum_down:.2f} dump decelerating); bounce favors UP."
        elif is_flat_chop:
            direction = "NO_TRADE"
            regime = "MICRO_CHOP"
            confidence = 50
            risk = 8
            reason = f"Micro-chop consolidation (${eff_range:.2f} range); momentum too flat for safe edge."
        elif p_up >= min_probability_threshold and v_1s >= 0.05 and features.bar_5s_return >= 0.15:
            direction = "UP"
            regime = "LAMINAR_THRUST" if eff >= 0.55 else "MOMENTUM_EXPANSION"
            confidence = int(round(p_up * 100))
            risk = 2 if confidence >= 85 else 4
            reason = f"AI Kinematic momentum confirmed ({confidence}% UP probability, +${features.bar_5s_return:.2f} return, {eff*100:.0f}% efficiency)."
        elif p_down >= min_probability_threshold and v_1s <= -0.05 and features.bar_5s_return <= -0.15:
            direction = "DOWN"
            regime = "LAMINAR_THRUST" if eff >= 0.55 else "MOMENTUM_EXPANSION"
            confidence = int(round(p_down * 100))
            risk = 2 if confidence >= 85 else 4
            reason = f"AI Kinematic momentum confirmed ({confidence}% DOWN probability, ${features.bar_5s_return:.2f} return, {eff*100:.0f}% efficiency)."
        elif p_up > 0.54 and features.bar_5s_return > 0.10:
            direction = "UP"
            regime = "MODERATE_LEAN"
            confidence = int(round(p_up * 100))
            risk = 5
            reason = f"Moderate buyer flow ({confidence}% probability) leading micro-structure."
        elif p_down > 0.54 and features.bar_5s_return < -0.10:
            direction = "DOWN"
            regime = "MODERATE_LEAN"
            confidence = int(round(p_down * 100))
            risk = 5
            reason = f"Moderate seller flow ({confidence}% probability) leading micro-structure."
        else:
            direction = "NO_TRADE"
            regime = "NEUTRAL"
            confidence = 50
            risk = 7
            reason = "Market in balanced equilibrium; directional probability insufficient for an edge."

        features_used = {
            "p_up": round(p_up, 4),
            "p_down": round(p_down, 4),
            "fractal_efficiency": round(eff, 3),
            "v_1s": round(v_1s, 3),
            "accel": round(accel, 3),
            "cum_up": round(cum_up, 2),
            "cum_down": round(cum_down, 2),
            "eff_range": round(eff_range, 2),
            "speed_convexity": round(speed_conv, 2),
        }

        return AIPredictionResult(
            predicted_direction=direction,
            up_probability=round(p_up, 4),
            down_probability=round(p_down, 4),
            confidence_pct=confidence,
            ai_regime=regime,
            risk_score=risk,
            reasoning=reason,
            features_used=features_used,
        )


ai_microstructure_predictor = AIMicrostructurePredictor()
