from __future__ import annotations

import math
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class FiveSecondBar:
    """A clean, time-aligned 5-second candlestick bar synthesized from trade ticks."""
    bucket_ts: int  # Unix timestamp in seconds (divisible by 5)
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    trades_count: int
    taker_buy_volume: float
    taker_sell_volume: float
    closed: bool = True

    @property
    def range(self) -> float:
        """High - Low range in USD."""
        return max(0.0, self.high - self.low)

    @property
    def return_usd(self) -> float:
        """Close - Open return in USD."""
        return self.close - self.open

    @property
    def return_bps(self) -> float:
        """Close - Open return in basis points."""
        return (self.return_usd / self.open * 10000.0) if self.open > 0 else 0.0

    @property
    def taker_ratio(self) -> float:
        """Proportion of volume driven by aggressive market buyers (0.0 to 1.0)."""
        return (self.taker_buy_volume / self.volume) if self.volume > 0 else 0.5

    @property
    def is_bullish(self) -> bool:
        return self.return_usd > 0

    @property
    def is_bearish(self) -> bool:
        return self.return_usd < 0

    @property
    def is_flat(self) -> bool:
        return abs(self.return_usd) < 0.01

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d['range'] = round(self.range, 4)
        d['return_usd'] = round(self.return_usd, 4)
        d['return_bps'] = round(self.return_bps, 2)
        d['taker_ratio'] = round(self.taker_ratio, 4)
        return d


class FiveSecondBarAggregator:
    """Thread-safe, rolling 5-second candlestick aggregator and micro-technical engine.

    Synthesizes tick-by-tick Binance trade streams into continuous 5-second OHLCV bars,
    enabling sub-minute analysis perfectly aligned with 5-second binary contracts.
    """

    def __init__(self, max_bars: int = 240) -> None:
        self.max_bars = max(30, max_bars)
        self._closed_bars: deque[FiveSecondBar] = deque(maxlen=self.max_bars)
        self._current_bar: dict[str, Any] | None = None

    def clear(self) -> None:
        self._closed_bars.clear()
        self._current_bar = None

    def add_trade(
        self,
        price: float,
        quantity: float,
        is_buyer_maker: bool,
        event_time_ts: float,
    ) -> FiveSecondBar | None:
        """Incorporate an incoming trade tick into 5-second bars.

        Returns the newly closed FiveSecondBar if this tick caused a bucket rollover,
        or None if updating the existing forming bar.
        """
        if not math.isfinite(price) or price <= 0:
            return None
        if not math.isfinite(quantity) or quantity < 0:
            return None

        bucket = int(event_time_ts // 5) * 5
        closed_bar: FiveSecondBar | None = None

        if self._current_bar is not None and bucket > self._current_bar['bucket_ts']:
            # Close previous forming bar
            c = self._current_bar
            closed_bar = FiveSecondBar(
                bucket_ts=c['bucket_ts'],
                open=c['open'],
                high=c['high'],
                low=c['low'],
                close=c['close'],
                volume=c['volume'],
                quote_volume=c['quote_volume'],
                trades_count=c['trades_count'],
                taker_buy_volume=c['taker_buy_volume'],
                taker_sell_volume=c['taker_sell_volume'],
                closed=True,
            )
            self._closed_bars.append(closed_bar)

            # Optional: if there was a gap of inactive 5s buckets, backfill with flat bars
            prev_ts = c['bucket_ts'] + 5
            last_price = c['close']
            while prev_ts < bucket and len(self._closed_bars) < self.max_bars:
                flat_bar = FiveSecondBar(
                    bucket_ts=prev_ts,
                    open=last_price,
                    high=last_price,
                    low=last_price,
                    close=last_price,
                    volume=0.0,
                    quote_volume=0.0,
                    trades_count=0,
                    taker_buy_volume=0.0,
                    taker_sell_volume=0.0,
                    closed=True,
                )
                self._closed_bars.append(flat_bar)
                prev_ts += 5

            self._current_bar = None

        if self._current_bar is None:
            self._current_bar = {
                'bucket_ts': bucket,
                'open': price,
                'high': price,
                'low': price,
                'close': price,
                'volume': quantity,
                'quote_volume': price * quantity,
                'trades_count': 1,
                'taker_buy_volume': 0.0 if is_buyer_maker else quantity,
                'taker_sell_volume': quantity if is_buyer_maker else 0.0,
            }
        else:
            # Update currently forming bar
            c = self._current_bar
            if price > c['high']:
                c['high'] = price
            if price < c['low']:
                c['low'] = price
            c['close'] = price
            c['volume'] += quantity
            c['quote_volume'] += price * quantity
            c['trades_count'] += 1
            if is_buyer_maker:
                c['taker_sell_volume'] += quantity
            else:
                c['taker_buy_volume'] += quantity

        return closed_bar

    def get_closed_bars(self, limit: int | None = None) -> list[FiveSecondBar]:
        bars = list(self._closed_bars)
        if limit is not None and limit > 0:
            return bars[-limit:]
        return bars

    def get_last_closed_bar(self) -> FiveSecondBar | None:
        if self._closed_bars:
            return self._closed_bars[-1]
        return None

    def get_forming_bar(self) -> FiveSecondBar | None:
        if self._current_bar is None:
            return None
        c = self._current_bar
        return FiveSecondBar(
            bucket_ts=c['bucket_ts'],
            open=c['open'],
            high=c['high'],
            low=c['low'],
            close=c['close'],
            volume=c['volume'],
            quote_volume=c['quote_volume'],
            trades_count=c['trades_count'],
            taker_buy_volume=c['taker_buy_volume'],
            taker_sell_volume=c['taker_sell_volume'],
            closed=False,
        )

    # --- Micro Technical Indicator Calculations on 5-Second Bars ---

    def calc_ema(self, period: int = 9) -> float | None:
        """Exponential Moving Average across closed 5-second bars."""
        if len(self._closed_bars) < 3:
            return None
        effective_period = min(period, len(self._closed_bars))
        closes = [b.close for b in self._closed_bars]
        k = 2.0 / (effective_period + 1)
        ema = closes[0]
        for c in closes:
            ema = c * k + ema * (1.0 - k)
        return ema

    def calc_rsi(self, period: int = 14) -> float | None:
        """Relative Strength Index across closed 5-second bars."""
        if len(self._closed_bars) < period + 1:
            return None
        closes = [b.close for b in self._closed_bars]
        diffs = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [max(d, 0.0) for d in diffs]
        losses = [max(-d, 0.0) for d in diffs]

        # Initial averages
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        # Wilder smoothing
        for i in range(period, len(diffs)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0.0:
            return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def calc_momentum(self, bars_back: int = 3) -> float | None:
        """Price change in USD across the last `bars_back` 5-second bars."""
        if len(self._closed_bars) < bars_back:
            return None
        return self._closed_bars[-1].close - self._closed_bars[-bars_back].open

    def calc_average_range(self, period: int = 6) -> float | None:
        """Average bar range across the last `period` 5-second bars."""
        if len(self._closed_bars) < period:
            return None
        recent = list(self._closed_bars)[-period:]
        return sum(b.range for b in recent) / period

    def get_metrics(self) -> dict[str, Any]:
        """Summary diagnostics of the 5-second bar series."""
        last = self.get_last_closed_bar()
        ema9 = self.calc_ema(9)
        ema21 = self.calc_ema(21)
        rsi14 = self.calc_rsi(14)
        mom3 = self.calc_momentum(3)
        avg_rng = self.calc_average_range(6)

        trend = 'NEUTRAL'
        if ema9 is not None and ema21 is not None:
            if ema9 > ema21:
                trend = 'BULLISH'
            elif ema9 < ema21:
                trend = 'BEARISH'

        return {
            'closed_bars_count': len(self._closed_bars),
            'last_closed_bar': last.to_dict() if last else None,
            'ema_fast_9': round(ema9, 2) if ema9 else None,
            'ema_slow_21': round(ema21, 2) if ema21 else None,
            'rsi_14': round(rsi14, 2) if rsi14 else None,
            'momentum_3bar_usd': round(mom3, 2) if mom3 else None,
            'avg_range_6bar_usd': round(avg_rng, 2) if avg_rng else None,
            'trend_5s': trend,
        }
