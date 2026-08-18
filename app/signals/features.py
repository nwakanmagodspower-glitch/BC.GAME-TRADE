from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from statistics import mean, pstdev

from app.integrations.market_data.base import Candle, MarketTick


@dataclass(frozen=True)
class FeatureSnapshot:
    # Slow/context features
    ema_fast: float
    ema_slow: float
    rsi_14: float
    atr_14_pct: float
    volume_ratio: float
    taker_buy_ratio: float
    structure: str
    distance_to_recent_high_pct: float
    distance_to_recent_low_pct: float

    # Primary five-second microstructure features
    trade_buy_ratio: float | None
    trade_count_recent: int
    tick_return_1s_pct: float
    tick_return_3s_pct: float
    tick_return_5s_pct: float
    tick_acceleration_pct: float
    tick_volatility_5s_pct: float

    def to_dict(self) -> dict:
        return asdict(self)


def _ema(values: list[float], period: int) -> float:
    alpha = 2 / (period + 1)
    value = values[0]
    for current in values[1:]:
        value = (current * alpha) + (value * (1 - alpha))
    return value


def _rsi(closes: list[float], period: int = 14) -> float:
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    recent = deltas[-period:]
    gains = sum(max(delta, 0.0) for delta in recent) / period
    losses = sum(max(-delta, 0.0) for delta in recent) / period
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    rs = gains / losses
    return 100.0 - (100.0 / (1.0 + rs))


def _atr_pct(candles: list[Candle], period: int = 14) -> float:
    trs = []
    for previous, current in zip(candles[-period - 1:-1], candles[-period:]):
        trs.append(max(current.high-current.low, abs(current.high-previous.close), abs(current.low-previous.close)))
    return mean(trs) / candles[-1].close * 100.0


def _structure(candles: list[Candle]) -> str:
    recent = candles[-6:]
    highs = [c.high for c in recent]; lows = [c.low for c in recent]
    hh = sum(b > a for a, b in zip(highs, highs[1:])); hl = sum(b > a for a, b in zip(lows, lows[1:]))
    lh = sum(b < a for a, b in zip(highs, highs[1:])); ll = sum(b < a for a, b in zip(lows, lows[1:]))
    if hh >= 3 and hl >= 3: return 'BULLISH'
    if lh >= 3 and ll >= 3: return 'BEARISH'
    return 'RANGE'


def _trade_buy_ratio(ticks: list[MarketTick]) -> float | None:
    classified = [t for t in ticks if t.is_buyer_maker is not None and t.quantity > 0]
    if not classified:
        return None
    buy_qty = sum(t.quantity for t in classified if t.is_buyer_maker is False)
    sell_qty = sum(t.quantity for t in classified if t.is_buyer_maker is True)
    total = buy_qty + sell_qty
    return buy_qty / total if total > 0 else None


def _window_ticks(ticks: list[MarketTick], seconds: int) -> list[MarketTick]:
    if not ticks:
        return []
    end = max(t.event_time for t in ticks)
    cutoff = end - timedelta(seconds=seconds)
    return [t for t in ticks if t.event_time >= cutoff]


def _return_pct(ticks: list[MarketTick], seconds: int) -> float:
    window = _window_ticks(ticks, seconds)
    if len(window) < 2 or not window[0].price:
        return 0.0
    return (window[-1].price / window[0].price - 1.0) * 100.0


def _micro_volatility_pct(ticks: list[MarketTick], seconds: int = 5) -> float:
    window = _window_ticks(ticks, seconds)
    if len(window) < 3:
        return 0.0
    returns = []
    for a, b in zip(window, window[1:]):
        if a.price:
            returns.append((b.price / a.price - 1.0) * 100.0)
    return pstdev(returns) if len(returns) >= 2 else 0.0


def build_features(candles: list[Candle], recent_ticks: list[MarketTick]) -> FeatureSnapshot:
    closed = [c for c in candles if c.closed]
    if len(closed) < 55:
        raise ValueError('at least 55 closed candles are required')

    closes = [c.close for c in closed]
    latest = closed[-1]
    recent_20 = closed[-20:]
    volume_baseline = mean(c.volume for c in closed[-21:-1]) or 1.0
    recent_high = max(c.high for c in recent_20); recent_low = min(c.low for c in recent_20)
    price = latest.close
    taker_ratio = latest.taker_buy_base_volume / latest.volume if latest.volume > 0 else 0.5

    r1 = _return_pct(recent_ticks, 1)
    r3 = _return_pct(recent_ticks, 3)
    r5 = _return_pct(recent_ticks, 5)

    return FeatureSnapshot(
        ema_fast=_ema(closes[-30:], 9),
        ema_slow=_ema(closes[-55:], 21),
        rsi_14=_rsi(closes, 14),
        atr_14_pct=_atr_pct(closed, 14),
        volume_ratio=latest.volume / volume_baseline,
        taker_buy_ratio=taker_ratio,
        structure=_structure(closed),
        distance_to_recent_high_pct=(recent_high-price)/price*100.0 if price else 0.0,
        distance_to_recent_low_pct=(price-recent_low)/price*100.0 if price else 0.0,
        trade_buy_ratio=_trade_buy_ratio(recent_ticks),
        trade_count_recent=len(recent_ticks),
        tick_return_1s_pct=r1,
        tick_return_3s_pct=r3,
        tick_return_5s_pct=r5,
        tick_acceleration_pct=r1 - (r5 / 5.0),
        tick_volatility_5s_pct=_micro_volatility_pct(recent_ticks, 5),
    )
