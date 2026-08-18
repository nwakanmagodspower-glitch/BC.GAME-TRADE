from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.integrations.market_data.base import Candle
from app.models.entities import SignalDirection
from app.signals.decision import decide
from app.signals.features import build_features
from app.signals.scoring import score_features


@dataclass(frozen=True)
class BacktestTrade:
    decision_time: datetime
    entry_time: datetime
    expiry_time: datetime
    direction: SignalDirection
    quality: str
    bull_score: int
    bear_score: int
    entry_price: float
    expiry_price: float
    outcome: str
    features: dict


@dataclass(frozen=True)
class BacktestReport:
    observations: int
    signals: int
    no_trades: int
    wins: int
    losses: int
    ties: int
    win_rate_ex_ties: float | None
    coverage_pct: float
    up_signals: int
    down_signals: int
    trades: list[BacktestTrade]


def _outcome(direction: SignalDirection, entry: float, expiry: float) -> str:
    if expiry == entry:
        return 'TIE'
    if direction == SignalDirection.UP:
        return 'WIN' if expiry > entry else 'LOSS'
    return 'WIN' if expiry < entry else 'LOSS'


def run_backtest(
    candles: list[Candle],
    *,
    expiry_minutes: int = 5,
    min_score: int = 6,
    min_margin: int = 3,
    warmup_candles: int = 60,
) -> BacktestReport:
    """Backtest the live V1 scoring rules without future-data leakage.

    Decision uses candles through index i only. Entry is the open of i+1.
    Expiry is the open exactly `expiry_minutes` one-minute candles after entry.
    Historical trade-flow is intentionally absent; build_features receives no ticks.
    """
    closed = [c for c in candles if c.closed]
    if expiry_minutes < 1:
        raise ValueError('expiry_minutes must be positive')
    if len(closed) < warmup_candles + expiry_minutes + 2:
        raise ValueError('not enough closed candles for backtest')

    trades: list[BacktestTrade] = []
    observations = 0
    no_trades = 0

    # i is the final candle visible to the strategy at decision time.
    last_i = len(closed) - expiry_minutes - 2
    for i in range(warmup_candles - 1, last_i + 1):
        history = closed[: i + 1]
        observations += 1

        features = build_features(history, [])
        score = score_features(features)
        decision = decide(score, min_score=min_score, min_margin=min_margin)

        if decision.direction == SignalDirection.NO_TRADE:
            no_trades += 1
            continue

        entry_candle = closed[i + 1]
        expiry_candle = closed[i + 1 + expiry_minutes]
        entry_price = entry_candle.open
        expiry_price = expiry_candle.open
        outcome = _outcome(decision.direction, entry_price, expiry_price)

        trades.append(
            BacktestTrade(
                decision_time=closed[i].close_time,
                entry_time=entry_candle.open_time,
                expiry_time=expiry_candle.open_time,
                direction=decision.direction,
                quality=decision.quality,
                bull_score=decision.bull_score,
                bear_score=decision.bear_score,
                entry_price=entry_price,
                expiry_price=expiry_price,
                outcome=outcome,
                features=features.to_dict(),
            )
        )

    wins = sum(t.outcome == 'WIN' for t in trades)
    losses = sum(t.outcome == 'LOSS' for t in trades)
    ties = sum(t.outcome == 'TIE' for t in trades)
    resolved = wins + losses
    win_rate = (wins / resolved * 100.0) if resolved else None
    coverage = (len(trades) / observations * 100.0) if observations else 0.0

    return BacktestReport(
        observations=observations,
        signals=len(trades),
        no_trades=no_trades,
        wins=wins,
        losses=losses,
        ties=ties,
        win_rate_ex_ties=win_rate,
        coverage_pct=coverage,
        up_signals=sum(t.direction == SignalDirection.UP for t in trades),
        down_signals=sum(t.direction == SignalDirection.DOWN for t in trades),
        trades=trades,
    )
