from __future__ import annotations

from dataclasses import dataclass, asdict
from statistics import mean

from app.integrations.market_data.base import Candle, MarketTick


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


def build_features(candles: list[Candle], recent_ticks: list[MarketTick]) -> FeatureSnapshot:
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

    return FeatureSnapshot(
        ema_fast=_ema(closes[-30:], 9),
        ema_slow=_ema(closes[-55:], 21),
        rsi_14=_rsi(closes, 14),
        atr_14_pct=_atr_pct(closed, 14),
        momentum_5_pct=((price / closes[-6]) - 1.0) * 100.0 if closes[-6] else 0.0,
        volume_ratio=latest.volume / volume_baseline,
        taker_buy_ratio=taker_ratio,
        structure=_structure(closed),
        distance_to_recent_high_pct=((recent_high - price) / price) * 100.0 if price else 0.0,
        distance_to_recent_low_pct=((price - recent_low) / price) * 100.0 if price else 0.0,
        trade_buy_ratio=_trade_buy_ratio(recent_ticks),
        trade_count_recent=len(recent_ticks),
    )
