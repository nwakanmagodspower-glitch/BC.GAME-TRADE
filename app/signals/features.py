from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import mean

from app.integrations.market_data.base import Candle, MarketTick
from app.signals.contracts import PredictionTarget, ScanStage


@dataclass(frozen=True)
class FeatureSnapshot:
    ema_fast: float
    ema_slow: float
    rsi_14: float
    atr_14_pct: float
    momentum_5_pct: float
    volume_ratio: float
    taker_buy_ratio: float
    structure: str
    distance_to_recent_high_pct: float
    distance_to_recent_low_pct: float
    trade_buy_ratio: float | None
    trade_count_recent: int
    target_round_id: str | None = None
    target_lead_time_seconds: float | None = None
    target_duration_seconds: float | None = None
    target_stage: str | None = None
    impulse_exhaustion_risk: bool = False
    trend_persistence_score: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _ema(values: list[float], period: int) -> float:
    if not values:
        raise ValueError('values required')
    alpha = 2 / (period + 1)
    value = values[0]
    for current in values[1:]:
        value = (current * alpha) + (value * (1 - alpha))
    return value


def _rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        raise ValueError('not enough closes for RSI')
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    recent = deltas[-period:]
    gains = sum(max(delta, 0.0) for delta in recent) / period
    losses = sum(max(-delta, 0.0) for delta in recent) / period
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    rs = gains / losses
    return 100.0 - (100.0 / (1.0 + rs))


def _atr_pct(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < period + 1:
        raise ValueError('not enough candles for ATR')
    trs: list[float] = []
    for previous, current in zip(candles[-period - 1:-1], candles[-period:]):
        tr = max(
            current.high - current.low,
            abs(current.high - previous.close),
            abs(current.low - previous.close),
        )
        trs.append(tr)
    close = candles[-1].close
    return (mean(trs) / close * 100.0) if close else 0.0


def _structure(candles: list[Candle]) -> str:
    if len(candles) < 6:
        return 'UNKNOWN'
    recent = candles[-6:]
    highs = [c.high for c in recent]
    lows = [c.low for c in recent]
    higher_highs = sum(1 for a, b in zip(highs, highs[1:]) if b > a)
    higher_lows = sum(1 for a, b in zip(lows, lows[1:]) if b > a)
    lower_highs = sum(1 for a, b in zip(highs, highs[1:]) if b < a)
    lower_lows = sum(1 for a, b in zip(lows, lows[1:]) if b < a)
    if higher_highs >= 3 and higher_lows >= 3:
        return 'BULLISH'
    if lower_highs >= 3 and lower_lows >= 3:
        return 'BEARISH'
    return 'RANGE'


def _trade_buy_ratio(ticks: list[MarketTick]) -> float | None:
    classified = [tick for tick in ticks if tick.is_buyer_maker is not None and tick.quantity > 0]
    if not classified:
        return None
    buy_qty = sum(t.quantity for t in classified if t.is_buyer_maker is False)
    sell_qty = sum(t.quantity for t in classified if t.is_buyer_maker is True)
    total = buy_qty + sell_qty
    return buy_qty / total if total > 0 else None


def build_features(
    candles: list[Candle],
    recent_ticks: list[MarketTick],
    *,
    target: PredictionTarget | None = None,
) -> FeatureSnapshot:
    closed = [candle for candle in candles if candle.closed]
    if len(closed) < 55:
        raise ValueError('at least 55 closed candles are required')

    closes = [c.close for c in closed]
    latest = closed[-1]
    recent_20 = closed[-20:]
    volume_baseline = mean(c.volume for c in closed[-21:-1]) or 1.0
    recent_high = max(c.high for c in recent_20)
    recent_low = min(c.low for c in recent_20)
    price = latest.close

    taker_total = latest.volume or 0.0
    taker_ratio = latest.taker_buy_base_volume / taker_total if taker_total > 0 else 0.5

    fast_ema = _ema(closes[-30:], 9)
    slow_ema = _ema(closes[-55:], 21)
    rsi_val = _rsi(closes, 14)
    atr_val = _atr_pct(closed, 14)
    mom_5 = ((price / closes[-6]) - 1.0) * 100.0 if closes[-6] else 0.0
    struct_val = _structure(closed)
    dist_high = ((recent_high - price) / price) * 100.0 if price else 0.0
    dist_low = ((price - recent_low) / price) * 100.0 if price else 0.0
    trade_ratio = _trade_buy_ratio(recent_ticks)

    target_round_id = target.round_id if target else None
    target_lead_time = target.lead_time_seconds if target else None
    target_duration = target.duration_seconds if target else None
    target_stage = target.scan_stage.value if target else None

    exhaustion_risk = False
    persistence_score = 0
    if target is not None and target_lead_time is not None:
        # Evaluate impulse exhaustion across the lead gap:
        # If the contract start T1 is in the future (>3s), an extreme impulse at T0
        # is prone to climax and retrace BEFORE or during [T1, T2].
        if target_lead_time > 3.0:
            if rsi_val >= 75.0 or (taker_ratio >= 0.75 and dist_high <= 0.02):
                exhaustion_risk = True
            elif rsi_val <= 25.0 or (taker_ratio <= 0.25 and dist_low <= 0.02):
                exhaustion_risk = True

        # Structural momentum persistence:
        ema_bull = fast_ema > slow_ema
        ema_bear = fast_ema < slow_ema
        mom_bull = mom_5 >= 0.08
        mom_bear = mom_5 <= -0.08

        if struct_val == 'BULLISH' and ema_bull and mom_bull and not exhaustion_risk:
            persistence_score = 2
        elif struct_val == 'BEARISH' and ema_bear and mom_bear and not exhaustion_risk:
            persistence_score = 2
        elif exhaustion_risk:
            persistence_score = -2
        elif struct_val == 'RANGE' and target_lead_time > 6.0:
            persistence_score = -1

    return FeatureSnapshot(
        ema_fast=fast_ema,
        ema_slow=slow_ema,
        rsi_14=rsi_val,
        atr_14_pct=atr_val,
        momentum_5_pct=mom_5,
        volume_ratio=latest.volume / volume_baseline,
        taker_buy_ratio=taker_ratio,
        structure=struct_val,
        distance_to_recent_high_pct=dist_high,
        distance_to_recent_low_pct=dist_low,
        trade_buy_ratio=trade_ratio,
        trade_count_recent=len(recent_ticks),
        target_round_id=target_round_id,
        target_lead_time_seconds=target_lead_time,
        target_duration_seconds=target_duration,
        target_stage=target_stage,
        impulse_exhaustion_risk=exhaustion_risk,
        trend_persistence_score=persistence_score,
    )
