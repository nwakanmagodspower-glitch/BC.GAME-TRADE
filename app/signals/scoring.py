from __future__ import annotations

from dataclasses import dataclass

from app.signals.features import FeatureSnapshot


@dataclass(frozen=True)
class ScoreResult:
    bull_score: int
    bear_score: int
    reasons: list[str]


def score_features(features: FeatureSnapshot) -> ScoreResult:
    bull = 0
    bear = 0
    reasons: list[str] = []

    if features.ema_fast > features.ema_slow:
        bull += 2
        reasons.append('fast EMA above slow EMA')
    elif features.ema_fast < features.ema_slow:
        bear += 2
        reasons.append('fast EMA below slow EMA')

    if features.momentum_5_pct >= 0.08:
        bull += 2
        reasons.append('positive 5-minute momentum')
    elif features.momentum_5_pct <= -0.08:
        bear += 2
        reasons.append('negative 5-minute momentum')

    if features.structure == 'BULLISH':
        bull += 2
        reasons.append('bullish short-term structure')
    elif features.structure == 'BEARISH':
        bear += 2
        reasons.append('bearish short-term structure')

    if features.volume_ratio >= 1.20:
        if features.taker_buy_ratio >= 0.55:
            bull += 1
            reasons.append('volume expansion with taker buying')
        elif features.taker_buy_ratio <= 0.45:
            bear += 1
            reasons.append('volume expansion with taker selling')

    if features.trade_buy_ratio is not None and features.trade_count_recent >= 5:
        if features.trade_buy_ratio >= 0.58:
            bull += 2
            reasons.append('recent trade flow favors buyers')
        elif features.trade_buy_ratio <= 0.42:
            bear += 2
            reasons.append('recent trade flow favors sellers')

    if features.lead_range_dollars >= 1.50:
        if features.lead_mom_dollars >= 0.50:
            bull += 1
            reasons.append(f'lead price expansion favors buyers (+${features.lead_mom_dollars:.2f})')
        elif features.lead_mom_dollars <= -0.50:
            bear += 1
            reasons.append(f'lead price expansion favors sellers (-${abs(features.lead_mom_dollars):.2f})')
    elif 0.0 < features.lead_range_dollars < 1.00:
        bull = max(0, bull - 1)
        bear = max(0, bear - 1)
        reasons.append('lead range < $1.00 indicates quiet chop')

    if 52 <= features.rsi_14 <= 72:
        bull += 1
        reasons.append('RSI supports bullish momentum without extreme extension')
    elif 28 <= features.rsi_14 <= 48:
        bear += 1
        reasons.append('RSI supports bearish momentum without extreme extension')

    if features.rsi_14 > 85:
        bull = max(0, bull - 1)
        reasons.append('bullish score reduced for overextension')
    elif features.rsi_14 < 15:
        bear = max(0, bear - 1)
        reasons.append('bearish score reduced for overextension')

    if features.atr_14_pct < 0.012:
        bull = max(0, bull - 1)
        bear = max(0, bear - 1)
        reasons.append('very low volatility reduces trade quality')
    elif features.atr_14_pct > 1.25:
        bull = max(0, bull - 2)
        bear = max(0, bear - 2)
        reasons.append('extreme volatility reduces trade quality')

    # Time-aligned horizon & lead-gap persistence evaluation:
    # Distinguish movement before contract start [T0, T1] from movement during contract [T1, T2]
    if features.target_lead_time_seconds is not None:
        if features.impulse_exhaustion_risk:
            if features.rsi_14 >= 74.0 or features.taker_buy_ratio >= 0.75:
                bull = max(0, bull - 3)
                reasons.append(
                    f'bullish impulse risk of exhaustion across {features.target_lead_time_seconds:.1f}s '
                    'lead gap before contract window [T1, T2]'
                )
            if features.rsi_14 <= 26.0 or features.taker_buy_ratio <= 0.25:
                bear = max(0, bear - 3)
                reasons.append(
                    f'bearish impulse risk of exhaustion across {features.target_lead_time_seconds:.1f}s '
                    'lead gap before contract window [T1, T2]'
                )
        elif features.trend_persistence_score == 2:
            reasons.append('structural trend persistence confirmed across lead gap into contract window')
        elif features.trend_persistence_score == -1:
            bull = max(0, bull - 1)
            bear = max(0, bear - 1)
            reasons.append('range structure with lead gap reduces contract window persistence')

    return ScoreResult(bull_score=bull, bear_score=bear, reasons=reasons)
