from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Sequence

from app.integrations.market_data.base import BookTicker, Candle, DepthSnapshot, MarketTick
from app.integrations.market_data.five_second_bar import FiveSecondBar, FiveSecondBarAggregator
from app.signals.features import _atr_pct, _ema, _rsi, _structure


@dataclass(frozen=True)
class MicrostructureFeatureSnapshot:
    # Slow regime context (from 1m candles if available, else 5s bars)
    ema_fast: float
    ema_slow: float
    rsi_14: float
    atr_14_pct: float
    momentum_5m_pct: float
    structure: str

    # Fast microstructure (Top-of-book & depth)
    mid_price: float
    spread: float
    spread_bps: float
    obi_top: float  # (bid_qty - ask_qty) / (bid_qty + ask_qty)
    obi_l5: float   # Weighted top 5 levels imbalance
    microprice: float
    microprice_dev_bps: float  # (microprice - mid_price) / mid_price * 10,000

    # Fast trade flow
    tfi_1s: float | None  # Trade flow imbalance over last 1s
    tfi_5s: float | None  # Trade flow imbalance over last 5s
    trade_count_1s: int
    trade_count_5s: int
    volume_5s: float

    # Short-term returns & velocity
    return_250ms_bps: float
    return_500ms_bps: float
    return_1s_bps: float
    return_2s_bps: float
    return_5s_bps: float
    velocity_1s_bps: float
    acceleration_1s_bps: float

    # Liquidity dynamics
    bid_depth_l5_qty: float
    ask_depth_l5_qty: float
    liquidity_delta_l5_pct: float  # 1s change in total top 5 depth

    # 5-Second Bar Micro-Regime (synthesized from trade ticks)
    bar_5s_return: float = 0.0
    bar_5s_range: float = 0.0
    bar_5s_taker_ratio: float = 0.5
    bar_5s_ema_fast: float = 0.0
    bar_5s_ema_slow: float = 0.0
    bar_5s_rsi_14: float = 50.0
    bar_5s_momentum_3bar: float = 0.0
    lead_range_dollars: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def calculate_obi_top(book: BookTicker) -> float:
    total = book.best_bid_qty + book.best_ask_qty
    if total <= 0:
        return 0.0
    return (book.best_bid_qty - book.best_ask_qty) / total


def calculate_obi_l5(depth: DepthSnapshot | None, fallback_book: BookTicker) -> float:
    if not depth or not depth.bids or not depth.asks:
        return calculate_obi_top(fallback_book)

    weights = [1.0, 0.5, 0.3333, 0.25, 0.2]
    weighted_bid_qty = sum(b.quantity * weights[i] for i, b in enumerate(depth.bids[:5]))
    weighted_ask_qty = sum(a.quantity * weights[i] for i, a in enumerate(depth.asks[:5]))

    total = weighted_bid_qty + weighted_ask_qty
    if total <= 0:
        return 0.0
    return (weighted_bid_qty - weighted_ask_qty) / total


def calculate_microprice(book: BookTicker) -> float:
    total_qty = book.best_bid_qty + book.best_ask_qty
    if total_qty <= 0:
        return book.mid_price
    # Microprice weighted by opposing depth
    return (book.best_bid_qty * book.best_ask_price + book.best_ask_qty * book.best_bid_price) / total_qty


def calculate_tfi(ticks: Sequence[MarketTick], now: datetime, lookback_seconds: float) -> tuple[float | None, int, float]:
    cutoff = now.timestamp() - lookback_seconds
    window_ticks = [t for t in ticks if t.event_time.timestamp() >= cutoff and t.quantity > 0]

    if not window_ticks:
        return None, 0, 0.0

    buy_qty = sum(t.quantity for t in window_ticks if t.is_buyer_maker is False)
    sell_qty = sum(t.quantity for t in window_ticks if t.is_buyer_maker is True)
    neutral_qty = sum(t.quantity for t in window_ticks if t.is_buyer_maker is None)
    total_qty = buy_qty + sell_qty + neutral_qty

    if total_qty <= 0:
        return 0.0, len(window_ticks), 0.0

    effective_buy = buy_qty + (neutral_qty * 0.5)
    effective_sell = sell_qty + (neutral_qty * 0.5)
    tfi = (effective_buy - effective_sell) / total_qty
    return tfi, len(window_ticks), total_qty


def _find_historical_price(
    books: Sequence[BookTicker],
    ticks: Sequence[MarketTick],
    target_time_ts: float,
) -> float | None:
    if books:
        candidates = [b for b in books if b.event_time.timestamp() <= target_time_ts]
        if candidates:
            return max(candidates, key=lambda b: b.event_time.timestamp()).mid_price
    if ticks:
        candidates = [t for t in ticks if t.event_time.timestamp() <= target_time_ts]
        if candidates:
            return max(candidates, key=lambda t: t.event_time.timestamp()).price
    return None


def _find_historical_mid(books: Sequence[BookTicker], target_time_ts: float) -> float | None:
    if not books:
        return None
    # Find closest book ticker before or at target_time_ts
    candidates = [b for b in books if b.event_time.timestamp() <= target_time_ts]
    if not candidates:
        return None
    closest = max(candidates, key=lambda b: b.event_time.timestamp())
    return closest.mid_price


def build_microstructure_features(
    candles: Sequence[Candle] | None = None,
    latest_book: BookTicker | None = None,
    book_history: Sequence[BookTicker] = (),
    depth: DepthSnapshot | None = None,
    depth_history: Sequence[DepthSnapshot] = (),
    recent_ticks: Sequence[MarketTick] = (),
    now: datetime | None = None,
    bars_5s: Sequence[FiveSecondBar] | None = None,
    bar_metrics_5s: dict[str, Any] | None = None,
    *,
    is_synthetic: bool = False,
) -> MicrostructureFeatureSnapshot:
    if latest_book is None:
        raise ValueError('latest_book is required for microstructure features')
    if now is None:
        now = datetime.now(timezone.utc)

    # 1. 5-Second Candlestick Synthesis & Micro-Regime
    if bars_5s is None and recent_ticks:
        agg = FiveSecondBarAggregator(max_bars=60)
        sorted_ticks = sorted(recent_ticks, key=lambda x: x.event_time.timestamp())
        for t in sorted_ticks:
            agg.add_trade(
                price=t.price,
                quantity=t.quantity,
                is_buyer_maker=bool(t.is_buyer_maker) if t.is_buyer_maker is not None else False,
                event_time_ts=t.event_time.timestamp(),
            )
        bars_5s = agg.get_closed_bars()
        if bar_metrics_5s is None:
            bar_metrics_5s = agg.get_metrics()

    last_5s_bar = bars_5s[-1] if bars_5s else None
    bar_5s_return = last_5s_bar.return_usd if last_5s_bar else 0.0
    bar_5s_range = last_5s_bar.range if last_5s_bar else 0.0
    bar_5s_taker_ratio = last_5s_bar.taker_ratio if last_5s_bar else 0.5

    b_metrics = bar_metrics_5s or {}
    mid = latest_book.mid_price
    bar_5s_ema_fast = float(b_metrics.get('ema_fast_9') or mid)
    bar_5s_ema_slow = float(b_metrics.get('ema_slow_21') or mid)
    bar_5s_rsi_14 = float(b_metrics.get('rsi_14') or 50.0)
    bar_5s_momentum_3bar = float(b_metrics.get('momentum_3bar_usd') or bar_5s_return)

    # 2. Slow Regime Context (1m candles if available and not pure synthetic, else 5s micro-regime)
    closed = [c for c in (candles or ()) if c.closed]
    if not is_synthetic and len(closed) >= 55:
        closes = [c.close for c in closed]
        price = closes[-1]
        ema_fast = _ema(closes[-30:], 9)
        ema_slow = _ema(closes[-55:], 21)
        rsi_14 = _rsi(closes, 14)
        atr_14_pct = _atr_pct(closed, 14)
        momentum_5m_pct = ((price / closes[-6]) - 1.0) * 100.0 if closes[-6] else 0.0
        structure = _structure(closed)
    else:
        ema_fast = bar_5s_ema_fast
        ema_slow = bar_5s_ema_slow
        rsi_14 = bar_5s_rsi_14
        atr_14_pct = (bar_5s_range / mid * 100.0) if mid > 0 else 0.05
        momentum_5m_pct = (bar_5s_momentum_3bar / mid * 100.0) if mid > 0 else 0.0
        structure = 'BULLISH' if bar_5s_return > 0 else ('BEARISH' if bar_5s_return < 0 else 'FLAT')

    # 3. Fast Microstructure Top-of-Book & Depth
    spread = latest_book.spread
    spread_bps = latest_book.spread_bps
    obi_top = calculate_obi_top(latest_book)
    obi_l5 = calculate_obi_l5(depth, latest_book)
    microprice = calculate_microprice(latest_book)
    microprice_dev_bps = ((microprice - mid) / mid * 10000.0) if mid > 0 else 0.0

    # 4. Fast Trade Flow
    tfi_1s, count_1s, _ = calculate_tfi(recent_ticks, now, lookback_seconds=1.0)
    tfi_5s, count_5s, vol_5s = calculate_tfi(recent_ticks, now, lookback_seconds=5.0)

    # 5. Returns, Velocity, Acceleration
    now_ts = now.timestamp()
    p_now = mid

    p_250ms = _find_historical_price(book_history, recent_ticks, now_ts - 0.25) or p_now
    p_500ms = _find_historical_price(book_history, recent_ticks, now_ts - 0.50) or p_now
    p_1s = _find_historical_price(book_history, recent_ticks, now_ts - 1.00) or p_now
    p_2s = _find_historical_price(book_history, recent_ticks, now_ts - 2.00) or p_now
    p_5s = _find_historical_price(book_history, recent_ticks, now_ts - 5.00) or p_now

    ret_250ms_bps = ((p_now - p_250ms) / p_250ms * 10000.0) if p_250ms > 0 else 0.0
    ret_500ms_bps = ((p_now - p_500ms) / p_500ms * 10000.0) if p_500ms > 0 else 0.0
    ret_1s_bps = ((p_now - p_1s) / p_1s * 10000.0) if p_1s > 0 else 0.0
    ret_2s_bps = ((p_now - p_2s) / p_2s * 10000.0) if p_2s > 0 else 0.0
    ret_5s_bps = ((p_now - p_5s) / p_5s * 10000.0) if p_5s > 0 else 0.0

    velocity_1s_bps = ret_1s_bps  # bps per 1s

    # Velocity 500ms ago
    p_1s_500ms_ago = _find_historical_price(book_history, recent_ticks, now_ts - 1.50) or p_500ms
    prev_velocity_1s_bps = ((p_500ms - p_1s_500ms_ago) / p_1s_500ms_ago * 10000.0) if p_1s_500ms_ago > 0 else 0.0
    acceleration_1s_bps = velocity_1s_bps - prev_velocity_1s_bps

    # 6. Liquidity Dynamics
    if depth and depth.bids and depth.asks:
        bid_depth_l5 = sum(b.quantity for b in depth.bids[:5])
        ask_depth_l5 = sum(a.quantity for a in depth.asks[:5])
    else:
        bid_depth_l5 = latest_book.best_bid_qty
        ask_depth_l5 = latest_book.best_ask_qty

    total_l5_now = bid_depth_l5 + ask_depth_l5

    # Historical depth 1s ago
    past_depths = [d for d in depth_history if d.event_time.timestamp() <= now_ts - 1.0]
    if past_depths:
        old_d = max(past_depths, key=lambda d: d.event_time.timestamp())
        old_bids = sum(b.quantity for b in old_d.bids[:5])
        old_asks = sum(a.quantity for a in old_d.asks[:5])
        old_total = old_bids + old_asks
        liquidity_delta_l5_pct = ((total_l5_now - old_total) / old_total * 100.0) if old_total > 0 else 0.0
    else:
        liquidity_delta_l5_pct = 0.0

    return MicrostructureFeatureSnapshot(
        bar_5s_return=bar_5s_return,
        bar_5s_range=bar_5s_range,
        lead_range_dollars=bar_5s_range,
        bar_5s_taker_ratio=bar_5s_taker_ratio,
        bar_5s_ema_fast=bar_5s_ema_fast,
        bar_5s_ema_slow=bar_5s_ema_slow,
        bar_5s_rsi_14=bar_5s_rsi_14,
        bar_5s_momentum_3bar=bar_5s_momentum_3bar,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        rsi_14=rsi_14,
        atr_14_pct=atr_14_pct,
        momentum_5m_pct=momentum_5m_pct,
        structure=structure,
        mid_price=mid,
        spread=spread,
        spread_bps=spread_bps,
        obi_top=obi_top,
        obi_l5=obi_l5,
        microprice=microprice,
        microprice_dev_bps=microprice_dev_bps,
        tfi_1s=tfi_1s,
        tfi_5s=tfi_5s,
        trade_count_1s=count_1s,
        trade_count_5s=count_5s,
        volume_5s=vol_5s,
        return_250ms_bps=ret_250ms_bps,
        return_500ms_bps=ret_500ms_bps,
        return_1s_bps=ret_1s_bps,
        return_2s_bps=ret_2s_bps,
        return_5s_bps=ret_5s_bps,
        velocity_1s_bps=velocity_1s_bps,
        acceleration_1s_bps=acceleration_1s_bps,
        bid_depth_l5_qty=bid_depth_l5,
        ask_depth_l5_qty=ask_depth_l5,
        liquidity_delta_l5_pct=liquidity_delta_l5_pct,
    )
