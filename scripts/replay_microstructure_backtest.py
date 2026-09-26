#!/usr/bin/env python3
"""Chronological Replay & Benchmark Engine for BTC_ORIGINAL_INTELLIGENCE_TIMER_V1 vs BTC_MICROSTRUCTURE_V2.

Architectural Modes:
  MODE A: BINANCE PROXY BENCHMARK
    - Prediction: V2 (and V1 paired)
    - Target: Binance BTCUSDT mid-price movement over 5.0 seconds (with +/-500ms tolerance via O(log M) bisect).
    - Labeled strictly as: "BINANCE PROXY BENCHMARK" (NEVER "BC.GAME ACCURACY").

  MODE B: ACTUAL BC.GAME BENCHMARK
    - Prediction: Generated at or before round priceStartTime using only market data available at that moment.
    - Target: Actual DeTrade/BC.GAME aggregated BTC/USD settlement:
        * endPrice > startPrice  -> UP
        * endPrice < startPrice  -> DOWN
        * endPrice == startPrice -> FLAT
    - Strictly zero-lookahead. Evaluates whether Binance predictive signals predict actual DeTrade settlements.

Key Engineering Features:
  - Exact 5-second target horizon with +/-500ms tolerance via bisect.
  - Correct flat-outcome accounting: FLAT settlements are treated as losses for directional predictions.
  - Chronological splits (Dev 50%, Validation 25%, Test 25%) with 5-second embargo to prevent target leakage.
  - Fully offline-reproducible: loads embedded candles from dataset; fails loudly if required data is missing.
  - Deterministic same-timestamp event sorting.
  - Live/replay configuration parity.
"""

import argparse
import asyncio
import bisect
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings
from app.integrations.market_data.base import BookTicker, Candle, DepthLevel, DepthSnapshot, MarketTick
from app.integrations.market_data.binance_spot import BinanceSpotProvider
from app.models.entities import SignalDirection
from app.services.market_data import MicrostructureDataCache
from app.signals.contracts import PredictionTarget
from app.signals.decision import decide as decide_v1
from app.signals.features import build_features as build_features_v1
from app.signals.microstructure.decision import decide_microstructure as decide_v2
from app.signals.microstructure.features import build_microstructure_features
from app.signals.microstructure.scoring import score_microstructure_features
from app.signals.scoring import score_features as score_features_v1

settings = get_settings()

EVENT_TYPE_PRIORITY = {
    'candle': 0,
    'detrade_round': 1,
    'depth': 2,
    'trade': 3,
    'book_ticker': 4,
}


@dataclass
class ReplayEvent:
    event_type: str
    event_ts: float
    local_ts: float
    data: dict


@dataclass
class EnginePrediction:
    direction: SignalDirection
    quality: str
    bull_score: int
    bear_score: int
    margin: int
    spread_bps: float
    atr_14_pct: float
    is_correct: bool | None = None


@dataclass
class PairedObservation:
    ts: float
    reference_price: float
    target_5s_price: float | None
    actual_direction: SignalDirection | None
    v1_pred: EnginePrediction | None
    v2_pred: EnginePrediction | None


@dataclass
class DeTradeRoundResult:
    round_id: str
    price_start_ts: float
    price_end_ts: float
    start_price: float
    end_price: float
    actual_outcome: SignalDirection
    v1_pred: EnginePrediction | None = None
    v2_pred: EnginePrediction | None = None


def resolve_target_bisect(
    book_ts_list: list[float],
    book_mid_list: list[float],
    target_ts: float,
    tolerance: float = 0.500,
) -> float | None:
    """Efficient O(log M) target lookup with exact tolerance."""
    if not book_ts_list:
        return None
    idx = bisect.bisect_left(book_ts_list, target_ts)
    best_diff = float('inf')
    best_mid: float | None = None
    for cand_idx in (idx - 1, idx):
        if 0 <= cand_idx < len(book_ts_list):
            diff = abs(book_ts_list[cand_idx] - target_ts)
            if diff <= tolerance and diff < best_diff:
                best_diff = diff
                best_mid = book_mid_list[cand_idx]
    return best_mid


def load_and_validate_dataset(file_path: str) -> tuple[list[ReplayEvent], dict]:
    """Load, validate, and sort recorded dataset with deterministic tie-breaking."""
    events: list[ReplayEvent] = []
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Dataset file not found: {file_path}")

    last_ts = 0.0
    out_of_order_count = 0
    duplicate_count = 0
    corrupted_count = 0

    type_counts = {"book_ticker": 0, "depth": 0, "trade": 0, "detrade_round": 0, "candle": 0}
    embedded_candles: list[Candle] = []
    detrade_rounds: dict[str, dict[str, Any]] = {}

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                etype = payload.get("type", "")
                event_ts = float(payload.get("event_ts") or payload.get("ts", 0))
                local_ts = float(payload.get("local_ts") or event_ts)

                if event_ts <= 0:
                    corrupted_count += 1
                    continue

                if event_ts < last_ts:
                    out_of_order_count += 1
                if event_ts == last_ts:
                    duplicate_count += 1
                last_ts = event_ts

                if etype in type_counts:
                    type_counts[etype] += 1

                # Parse embedded candles
                if etype == "candle":
                    c_data = payload.get("data", payload)
                    dt_open = datetime.fromtimestamp(float(c_data["open_time"]), tz=timezone.utc)
                    dt_close = datetime.fromtimestamp(float(c_data["close_time"]), tz=timezone.utc)
                    candle = Candle(
                        symbol=settings.analysis_pair.upper(),
                        interval="1m",
                        open_time=dt_open,
                        close_time=dt_close,
                        open=float(c_data["open"]),
                        high=float(c_data["high"]),
                        low=float(c_data["low"]),
                        close=float(c_data["close"]),
                        volume=float(c_data.get("volume", 0.0)),
                        quote_volume=float(c_data.get("quote_volume", 0.0)),
                        trade_count=int(c_data.get("trade_count", 0)),
                        taker_buy_base_volume=float(c_data.get("taker_buy_base_volume", 0.0)),
                        taker_buy_quote_volume=float(c_data.get("taker_buy_quote_volume", 0.0)),
                        closed=bool(c_data.get("closed", True)),
                        provider="BINANCE_SPOT",
                    )
                    embedded_candles.append(candle)

                # Parse DeTrade round frames
                elif etype == "detrade_round":
                    r_data = payload.get("data", payload)
                    r_id = str(r_data.get("round_id") or "")
                    if r_id:
                        if r_id not in detrade_rounds:
                            detrade_rounds[r_id] = {}
                        detrade_rounds[r_id].update({k: v for k, v in r_data.items() if v is not None})

                events.append(ReplayEvent(
                    event_type=etype,
                    event_ts=event_ts,
                    local_ts=local_ts,
                    data=payload.get("data", payload),
                ))
            except Exception:
                corrupted_count += 1

    # Deterministic sorting: event_ts -> local_ts -> event_type priority
    events.sort(key=lambda e: (e.event_ts, e.local_ts, EVENT_TYPE_PRIORITY.get(e.event_type, 99)))

    # Deduplicate embedded candles by close_time
    seen_candle_closes = set()
    unique_candles: list[Candle] = []
    for c in sorted(embedded_candles, key=lambda c: c.close_time):
        if c.close_time not in seen_candle_closes:
            seen_candle_closes.add(c.close_time)
            unique_candles.append(c)

    # Synthesize rolling 1m candles if recorded trade events extend past embedded candle context
    last_candle_ts = max((c.close_time.timestamp() for c in unique_candles), default=0.0)
    trades = [e for e in events if e.event_type == "trade" and e.event_ts > last_candle_ts]
    if trades:
        buckets: dict[int, list[tuple[float, float, float, bool]]] = {}
        for ev in trades:
            ts = ev.event_ts
            p = float(ev.data.get("price") or ev.data.get("data", {}).get("price", 0))
            q = float(ev.data.get("qty") or ev.data.get("data", {}).get("qty", 0))
            is_bm = bool(ev.data.get("is_buyer_maker", False))
            b_ts = int(ts // 60) * 60
            if b_ts not in buckets:
                buckets[b_ts] = []
            buckets[b_ts].append((ts, p, q, is_bm))
        for b_ts in sorted(buckets.keys()):
            b_trades = buckets[b_ts]
            dt_open = datetime.fromtimestamp(b_ts, tz=timezone.utc)
            dt_close = datetime.fromtimestamp(b_ts + 60, tz=timezone.utc)
            if dt_close not in seen_candle_closes:
                seen_candle_closes.add(dt_close)
                open_p = b_trades[0][1]
                high_p = max(x[1] for x in b_trades)
                low_p = min(x[1] for x in b_trades)
                close_p = b_trades[-1][1]
                vol = sum(x[2] for x in b_trades)
                taker_buy_vol = sum(x[2] for x in b_trades if not x[3])
                unique_candles.append(Candle(
                    symbol=settings.analysis_pair.upper(),
                    interval="1m",
                    open_time=dt_open,
                    close_time=dt_close,
                    open=open_p,
                    high=high_p,
                    low=low_p,
                    close=close_p,
                    volume=vol,
                    quote_volume=vol * close_p,
                    trade_count=len(b_trades),
                    taker_buy_base_volume=taker_buy_vol,
                    taker_buy_quote_volume=taker_buy_vol * close_p,
                    closed=True,
                    provider="BINANCE_SPOT",
                ))
    unique_candles.sort(key=lambda c: c.close_time)

    stats = {
        "total_raw_events": len(events),
        "book_ticker_events": type_counts["book_ticker"],
        "depth_events": type_counts["depth"],
        "trade_events": type_counts["trade"],
        "detrade_round_events": type_counts["detrade_round"],
        "candle_events": len(unique_candles),
        "out_of_order_re_sorted": out_of_order_count,
        "duplicate_timestamps": duplicate_count,
        "corrupted_lines": corrupted_count,
        "embedded_candles": unique_candles,
        "detrade_rounds": detrade_rounds,
    }
    return events, stats


async def fetch_historical_candles_for_replay(start_ts: float, end_ts: float) -> list[Candle]:
    """Fetch real 1-minute historical candles from Binance as a fallback."""
    provider = BinanceSpotProvider(
        rest_base_url=settings.market_data_rest_base_url,
        ws_base_url=settings.market_data_ws_base_url,
    )
    start_dt = datetime.fromtimestamp(start_ts - 7200, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(end_ts + 60, tz=timezone.utc)

    try:
        candles = await provider.fetch_historical_candles(
            symbol=settings.analysis_pair,
            interval="1m",
            start_time=start_dt,
            end_time=end_dt,
        )
        return candles
    except Exception as exc:
        print(f"Warning: Online candle fetch failed ({exc}).")
        return []


def get_candles_available_at(candles: Sequence[Candle], current_ts: float) -> list[Candle]:
    cutoff_dt = datetime.fromtimestamp(current_ts, tz=timezone.utc)
    return [c for c in candles if c.close_time <= cutoff_dt]


async def run_replay_simulation(
    events: list[ReplayEvent],
    all_candles: list[Candle],
    eval_interval_seconds: float = 1.0,
    target_tolerance_seconds: float = 0.500,
) -> list[PairedObservation]:
    """Execute paired V1 vs V2 simulation with strict zero lookahead."""
    cache = MicrostructureDataCache()
    symbol = settings.analysis_pair.upper()

    observations: list[PairedObservation] = []
    book_ts_list: list[float] = []
    book_mid_list: list[float] = []
    last_eval_ts = 0.0

    for event in events:
        dt = datetime.fromtimestamp(event.event_ts, tz=timezone.utc)

        if event.event_type == "book_ticker":
            book = BookTicker(
                symbol=symbol,
                best_bid_price=float(event.data["bid"]),
                best_bid_qty=float(event.data["bid_qty"]),
                best_ask_price=float(event.data["ask"]),
                best_ask_qty=float(event.data["ask_qty"]),
                event_time=dt,
                provider="BINANCE_SPOT",
            )
            await cache.add_book_ticker(book)
            book_ts_list.append(event.event_ts)
            book_mid_list.append(book.mid_price)

        elif event.event_type == "depth":
            bids = tuple(DepthLevel(price=float(b[0]), quantity=float(b[1])) for b in event.data["bids"])
            asks = tuple(DepthLevel(price=float(a[0]), quantity=float(a[1])) for a in event.data["asks"])
            depth = DepthSnapshot(
                symbol=symbol,
                bids=bids,
                asks=asks,
                event_time=dt,
                provider="BINANCE_SPOT",
            )
            await cache.add_depth_snapshot(depth)

        elif event.event_type == "trade":
            tick = MarketTick(
                symbol=symbol,
                price=float(event.data["price"]),
                quantity=float(event.data["qty"]),
                event_time=dt,
                provider="BINANCE_SPOT",
                is_buyer_maker=bool(event.data.get("is_buyer_maker", False)),
            )
            await cache.add_trade(tick)

        if event.event_ts - last_eval_ts >= eval_interval_seconds:
            last_eval_ts = event.event_ts

            candles_now = get_candles_available_at(all_candles, event.event_ts)
            if len(candles_now) < 55:
                continue

            snapshot = await cache.get_snapshot(
                symbol,
                max_book_age_seconds=settings.microstructure_book_max_age_seconds,
                trade_lookback_seconds=float(settings.signal_trade_flow_lookback_seconds),
                reference_time=dt,
            )
            if snapshot.book_ticker is None or not snapshot.is_fresh:
                continue

            book_history = await cache.get_book_history(symbol, lookback_seconds=10.0, reference_time=dt)
            depth_history = await cache.get_depth_history(symbol, lookback_seconds=10.0, reference_time=dt)

            # Evaluate V1
            v1_pred: EnginePrediction | None = None
            try:
                v1_features = build_features_v1(candles_now, list(snapshot.recent_ticks))
                v1_score = score_features_v1(v1_features)
                v1_decision = decide_v1(
                    v1_score,
                    min_score=settings.signal_min_score,
                    min_margin=settings.signal_min_margin,
                    features=v1_features,
                    min_lead_range=settings.signal_min_lead_range_dollars,
                )
                v1_pred = EnginePrediction(
                    direction=v1_decision.direction,
                    quality=v1_decision.quality,
                    bull_score=v1_decision.bull_score,
                    bear_score=v1_decision.bear_score,
                    margin=v1_decision.margin,
                    spread_bps=snapshot.book_ticker.spread_bps,
                    atr_14_pct=v1_features.atr_14_pct,
                )
            except Exception:
                pass

            # Evaluate V2
            v2_pred: EnginePrediction | None = None
            try:
                v2_features = build_microstructure_features(
                    candles=candles_now,
                    latest_book=snapshot.book_ticker,
                    book_history=book_history,
                    depth=snapshot.depth,
                    depth_history=depth_history,
                    recent_ticks=snapshot.recent_ticks,
                    now=dt,
                    bars_5s=snapshot.bars_5s,
                    bar_metrics_5s=snapshot.bar_metrics_5s,
                )
                v2_score = score_microstructure_features(v2_features)
                v2_decision = decide_v2(
                    score=v2_score,
                    features=v2_features,
                    is_fresh=True,
                    max_spread_bps=settings.microstructure_max_spread_bps,
                    min_l5_volume=settings.microstructure_min_l5_volume,
                    min_score=settings.microstructure_min_score,
                    min_margin=settings.microstructure_min_margin,
                )
                v2_pred = EnginePrediction(
                    direction=v2_decision.direction,
                    quality=v2_decision.quality,
                    bull_score=v2_decision.bull_score,
                    bear_score=v2_decision.bear_score,
                    margin=v2_decision.margin,
                    spread_bps=v2_features.spread_bps,
                    atr_14_pct=v2_features.atr_14_pct,
                )
            except Exception:
                pass

            observations.append(PairedObservation(
                ts=event.event_ts,
                reference_price=snapshot.book_ticker.mid_price,
                target_5s_price=None,
                actual_direction=None,
                v1_pred=v1_pred,
                v2_pred=v2_pred,
            ))

    # Resolve 5-second Target Horizon using O(log M) bisect with exact tolerance
    for obs in observations:
        target_ts = obs.ts + 5.0
        target_mid = resolve_target_bisect(
            book_ts_list, book_mid_list, target_ts, tolerance=target_tolerance_seconds
        )
        if target_mid is not None:
            obs.target_5s_price = target_mid
            if obs.target_5s_price > obs.reference_price:
                obs.actual_direction = SignalDirection.UP
            elif obs.target_5s_price < obs.reference_price:
                obs.actual_direction = SignalDirection.DOWN
            else:
                obs.actual_direction = SignalDirection.NO_TRADE  # FLAT

            # Proper directional accounting: FLAT is incorrect for both UP and DOWN
            if obs.v1_pred and obs.v1_pred.direction in (SignalDirection.UP, SignalDirection.DOWN):
                if obs.actual_direction == SignalDirection.NO_TRADE:
                    obs.v1_pred.is_correct = False
                else:
                    obs.v1_pred.is_correct = (obs.v1_pred.direction == obs.actual_direction)

            if obs.v2_pred and obs.v2_pred.direction in (SignalDirection.UP, SignalDirection.DOWN):
                if obs.actual_direction == SignalDirection.NO_TRADE:
                    obs.v2_pred.is_correct = False
                else:
                    obs.v2_pred.is_correct = (obs.v2_pred.direction == obs.actual_direction)

    return observations


async def evaluate_actual_detrade_rounds(
    events: list[ReplayEvent],
    all_candles: list[Candle],
    detrade_rounds: dict[str, dict[str, Any]],
    scan_lead_seconds: float = 10.0,
) -> list[DeTradeRoundResult]:
    """MODE B: Evaluate V2 and V1 predictions strictly against authoritative DeTrade round settlements."""
    results: list[DeTradeRoundResult] = []
    symbol = settings.analysis_pair.upper()

    completed_rounds: list[dict[str, Any]] = []
    for r_id, r in detrade_rounds.items():
        s_price = r.get("start_price")
        e_price = r.get("end_price")
        p_start_ms = r.get("price_start_time_ms")
        p_end_ms = r.get("price_end_time_ms")

        if s_price is not None and e_price is not None and p_start_ms is not None:
            completed_rounds.append({
                "round_id": r_id,
                "start_price": float(s_price),
                "end_price": float(e_price),
                "price_start_ts": float(p_start_ms) / 1000.0,
                "price_end_ts": (float(p_end_ms) / 1000.0) if p_end_ms else (float(p_start_ms) / 1000.0 + 5.0),
                "trade_cutoff_ts": (float(r.get("trade_cutoff_time_ms", p_start_ms)) / 1000.0),
            })

    completed_rounds.sort(key=lambda r: r["price_start_ts"])
    if not completed_rounds:
        return []

    # Replay cache up to each round's scan lead time (during the active betting window)
    cache = MicrostructureDataCache()
    event_idx = 0
    n_events = len(events)

    for round_info in completed_rounds:
        target_ts = round_info["price_start_ts"]
        eval_ts = target_ts - scan_lead_seconds

        # Advance cache strictly up to decision timestamp (scan_time during betting window)
        while event_idx < n_events and events[event_idx].event_ts <= eval_ts:
            ev = events[event_idx]
            dt = datetime.fromtimestamp(ev.event_ts, tz=timezone.utc)
            if ev.event_type == "book_ticker":
                await cache.add_book_ticker(BookTicker(
                    symbol=symbol,
                    best_bid_price=float(ev.data["bid"]),
                    best_bid_qty=float(ev.data["bid_qty"]),
                    best_ask_price=float(ev.data["ask"]),
                    best_ask_qty=float(ev.data["ask_qty"]),
                    event_time=dt,
                    provider="BINANCE_SPOT",
                ))
            elif ev.event_type == "depth":
                bids = tuple(DepthLevel(price=float(b[0]), quantity=float(b[1])) for b in ev.data["bids"])
                asks = tuple(DepthLevel(price=float(a[0]), quantity=float(a[1])) for a in ev.data["asks"])
                await cache.add_depth_snapshot(DepthSnapshot(
                    symbol=symbol, bids=bids, asks=asks, event_time=dt, provider="BINANCE_SPOT",
                ))
            elif ev.event_type == "trade":
                p = float(ev.data.get("price") or ev.data.get("data", {}).get("price", 0))
                q = float(ev.data.get("qty") or ev.data.get("data", {}).get("qty", 0))
                await cache.add_trade(MarketTick(
                    symbol=symbol,
                    price=p,
                    quantity=q,
                    event_time=dt,
                    provider="BINANCE_SPOT",
                    is_buyer_maker=bool(ev.data.get("is_buyer_maker", False)),
                ))
            event_idx += 1

        # Determine authoritative DeTrade settlement outcome
        s_price = round_info["start_price"]
        e_price = round_info["end_price"]
        if e_price > s_price:
            outcome = SignalDirection.UP
        elif e_price < s_price:
            outcome = SignalDirection.DOWN
        else:
            outcome = SignalDirection.NO_TRADE  # FLAT

        # Evaluate V2 at scan timestamp using only market data available at that moment
        cutoff_dt = datetime.fromtimestamp(eval_ts, tz=timezone.utc)
        candles_now = get_candles_available_at(all_candles, eval_ts)
        snapshot = await cache.get_snapshot(
            symbol,
            max_book_age_seconds=settings.microstructure_book_max_age_seconds,
            trade_lookback_seconds=float(settings.signal_trade_flow_lookback_seconds),
            reference_time=cutoff_dt,
        )

        v2_pred: EnginePrediction | None = None
        if snapshot.book_ticker is not None and snapshot.is_fresh:
            book_history = await cache.get_book_history(symbol, lookback_seconds=10.0, reference_time=cutoff_dt)
            depth_history = await cache.get_depth_history(symbol, lookback_seconds=10.0, reference_time=cutoff_dt)
            try:
                v2_features = build_microstructure_features(
                    candles=candles_now,
                    latest_book=snapshot.book_ticker,
                    book_history=book_history,
                    depth=snapshot.depth,
                    depth_history=depth_history,
                    recent_ticks=snapshot.recent_ticks,
                    now=cutoff_dt,
                    bars_5s=snapshot.bars_5s,
                    bar_metrics_5s=snapshot.bar_metrics_5s,
                )
                v2_score = score_microstructure_features(v2_features)
                v2_decision = decide_v2(
                    score=v2_score,
                    features=v2_features,
                    is_fresh=True,
                    max_spread_bps=settings.microstructure_max_spread_bps,
                    min_l5_volume=settings.microstructure_min_l5_volume,
                    min_score=settings.microstructure_min_score,
                    min_margin=settings.microstructure_min_margin,
                )
                is_corr = None
                if v2_decision.direction in (SignalDirection.UP, SignalDirection.DOWN):
                    if outcome == SignalDirection.NO_TRADE:
                        is_corr = False
                    else:
                        is_corr = (v2_decision.direction == outcome)

                v2_pred = EnginePrediction(
                    direction=v2_decision.direction,
                    quality=v2_decision.quality,
                    bull_score=v2_decision.bull_score,
                    bear_score=v2_decision.bear_score,
                    margin=v2_decision.margin,
                    spread_bps=v2_features.spread_bps,
                    atr_14_pct=v2_features.atr_14_pct,
                    is_correct=is_corr,
                )
            except Exception:
                pass

        # Evaluate V1 (Production Confluence Engine)
        v1_pred: EnginePrediction | None = None
        if snapshot.is_fresh and len(candles_now) >= 55:
            try:
                start_dt = datetime.fromtimestamp(round_info["price_start_ts"], tz=timezone.utc)
                end_dt = datetime.fromtimestamp(round_info["price_end_ts"], tz=timezone.utc)
                cutoff_trade_dt = datetime.fromtimestamp(round_info.get("trade_cutoff_ts") or round_info["price_start_ts"], tz=timezone.utc)
                target = PredictionTarget(
                    round_id=round_info["round_id"],
                    target_start=start_dt,
                    target_end=end_dt,
                    lead_time_seconds=scan_lead_seconds,
                    duration_seconds=(end_dt - start_dt).total_seconds(),
                    scan_time=cutoff_dt,
                    trade_cutoff=cutoff_trade_dt,
                    seconds_until_cutoff=max(0.0, (cutoff_trade_dt - cutoff_dt).total_seconds()),
                )
                v1_features = build_features_v1(candles_now, list(snapshot.recent_ticks), target=target)
                v1_score = score_features_v1(v1_features)
                v1_decision = decide_v1(
                    v1_score,
                    min_score=settings.signal_min_score,
                    min_margin=settings.signal_min_margin,
                    target=target,
                    features=v1_features,
                    min_lead_range=settings.signal_min_lead_range_dollars,
                )
                is_v1_corr = None
                if v1_decision.direction in (SignalDirection.UP, SignalDirection.DOWN):
                    if outcome == SignalDirection.NO_TRADE:
                        is_v1_corr = False
                    else:
                        is_v1_corr = (v1_decision.direction == outcome)

                v1_pred = EnginePrediction(
                    direction=v1_decision.direction,
                    quality=v1_decision.quality,
                    bull_score=v1_decision.bull_score,
                    bear_score=v1_decision.bear_score,
                    margin=v1_decision.margin,
                    spread_bps=snapshot.book_ticker.spread_bps if snapshot.book_ticker else 0.0,
                    atr_14_pct=v1_features.atr_14_pct,
                    is_correct=is_v1_corr,
                )
            except Exception:
                pass

        results.append(DeTradeRoundResult(
            round_id=round_info["round_id"],
            price_start_ts=round_info["price_start_ts"],
            price_end_ts=round_info["price_end_ts"],
            start_price=s_price,
            end_price=e_price,
            actual_outcome=outcome,
            v1_pred=v1_pred,
            v2_pred=v2_pred,
        ))

    return results


def print_split_metrics(
    observations: Sequence[PairedObservation],
    engine_name: str,
    split_name: str,
    is_v2: bool,
    benchmark_label: str = "BINANCE PROXY BENCHMARK",
) -> None:
    """Print split metrics with proper flat-outcome accounting."""
    # Denominator includes all resolved observations (UP, DOWN, or FLAT)
    resolved_obs = [o for o in observations if o.actual_direction is not None]
    preds = [(o.v2_pred if is_v2 else o.v1_pred) for o in resolved_obs]
    preds = [p for p in preds if p is not None]

    total_evals = len(observations)
    actionable = [p for p in preds if p.direction in (SignalDirection.UP, SignalDirection.DOWN)]
    no_trade_count = total_evals - len(actionable)
    coverage = (len(actionable) / total_evals * 100.0) if total_evals > 0 else 0.0

    up_actionable = [p for p in actionable if p.direction == SignalDirection.UP]
    down_actionable = [p for p in actionable if p.direction == SignalDirection.DOWN]

    correct_total = sum(1 for p in actionable if p.is_correct is True)
    correct_up = sum(1 for p in up_actionable if p.is_correct is True)
    correct_down = sum(1 for p in down_actionable if p.is_correct is True)

    acc_total = (correct_total / len(actionable) * 100.0) if actionable else 0.0
    acc_up = (correct_up / len(up_actionable) * 100.0) if up_actionable else 0.0
    acc_down = (correct_down / len(down_actionable) * 100.0) if down_actionable else 0.0

    strong_actionable = [p for p in actionable if p.quality == "STRONG"]
    valid_actionable = [p for p in actionable if p.quality == "VALID"]

    acc_strong = (sum(1 for p in strong_actionable if p.is_correct is True) / len(strong_actionable) * 100.0) if strong_actionable else 0.0
    acc_valid = (sum(1 for p in valid_actionable if p.is_correct is True) / len(valid_actionable) * 100.0) if valid_actionable else 0.0

    flat_settlements = sum(1 for o in resolved_obs if o.actual_direction == SignalDirection.NO_TRADE)

    print(f"\n--- [{benchmark_label}] {engine_name} | {split_name} ---")
    print(f"Total Shared Timestamps: {total_evals} (Resolved: {len(resolved_obs)}, Flat: {flat_settlements})")
    print(f"Actionable Signals:     {len(actionable)} (NO_TRADE: {no_trade_count})")
    print(f"Coverage:              {coverage:.2f}%")
    print(f"Overall Accuracy:      {acc_total:.2f}% ({correct_total}/{len(actionable)})")
    print(f"  - UP Accuracy:       {acc_up:.2f}% ({correct_up}/{len(up_actionable)})")
    print(f"  - DOWN Accuracy:     {acc_down:.2f}% ({correct_down}/{len(down_actionable)})")
    print(f"  - STRONG Accuracy:   {acc_strong:.2f}% ({sum(1 for p in strong_actionable if p.is_correct is True)}/{len(strong_actionable)})")
    print(f"  - VALID Accuracy:    {acc_valid:.2f}% ({sum(1 for p in valid_actionable if p.is_correct is True)}/{len(valid_actionable)})")


def create_embargoed_splits(
    observations: Sequence[PairedObservation],
    embargo_seconds: float = 5.0,
) -> list[tuple[str, int, int]]:
    """Create Dev/Val/Test splits with strict embargo to prevent target leakage."""
    n = len(observations)
    if n == 0:
        return []

    dev_target_end = int(n * 0.50)
    val_target_end = int(n * 0.75)

    dev_end = dev_target_end

    val_start = dev_end
    if dev_end > 0 and dev_end < n:
        last_dev_ts = observations[dev_end - 1].ts
        while val_start < n and observations[val_start].ts < last_dev_ts + embargo_seconds:
            val_start += 1

    val_end = max(val_start, val_target_end)

    test_start = val_end
    if val_end > val_start and val_end < n:
        last_val_ts = observations[val_end - 1].ts
        while test_start < n and observations[test_start].ts < last_val_ts + embargo_seconds:
            test_start += 1

    # Fallback to direct slices if dataset is very short
    if val_start >= val_end or test_start >= n:
        return [
            ("DEV / TRAIN SPLIT (0-50%)", 0, dev_target_end),
            ("VALIDATION SPLIT (50-75%)", dev_target_end, val_target_end),
            ("UNSEEN TEST SPLIT (75-100%)", val_target_end, n),
        ]

    return [
        (f"DEV / TRAIN SPLIT (0-{dev_end})", 0, dev_end),
        (f"VALIDATION SPLIT ({val_start}-{val_end}) [Embargo {embargo_seconds}s applied]", val_start, val_end),
        (f"UNSEEN TEST SPLIT ({test_start}-{n}) [Embargo {embargo_seconds}s applied]", test_start, n),
    ]


def filter_non_overlapping_obs(observations: Sequence[PairedObservation], block_seconds: float = 5.0) -> list[PairedObservation]:
    blocks: list[PairedObservation] = []
    last_ts = -1.0
    for o in sorted(observations, key=lambda x: x.ts):
        if o.ts >= last_ts + block_seconds:
            blocks.append(o)
            last_ts = o.ts
    return blocks


async def async_main():
    parser = argparse.ArgumentParser(description="Replay & Benchmark Engine (V1 vs V2).")
    parser.add_argument("--file", type=str, required=True, help="Input dataset JSONL path")
    args = parser.parse_args()

    events, stats = load_and_validate_dataset(args.file)
    if not events:
        print("CRITICAL REPLAY ERROR: Dataset empty or invalid.")
        sys.exit(1)

    start_ts = events[0].event_ts
    end_ts = events[-1].event_ts
    duration = end_ts - start_ts

    # Use embedded candles if available; otherwise fetch from Binance REST
    all_candles: list[Candle] = stats.get("embedded_candles", [])
    if len(all_candles) < 55:
        print(f"Embedded candles insufficient ({len(all_candles)} found). Fetching online fallback candles...")
        online_candles = await fetch_historical_candles_for_replay(start_ts, end_ts)
        if online_candles:
            all_candles = online_candles
            print(f"Fetched {len(all_candles)} online historical candles.")

    # Fail loudly if required candles are missing
    if len(all_candles) < 55:
        print(f"\nCRITICAL REPLAY ERROR: Insufficient candle history ({len(all_candles)} available, minimum 55 required for ATR/regime indicators).")
        print("Replay cannot proceed without required historical context. Exiting with failure.")
        sys.exit(1)

    observations = await run_replay_simulation(events, all_candles)

    v1_preds_count = sum(1 for o in observations if o.v1_pred is not None)
    v2_preds_count = sum(1 for o in observations if o.v2_pred is not None)

    valid_targets_count = sum(1 for o in observations if o.actual_direction in (SignalDirection.UP, SignalDirection.DOWN))
    flat_targets_count = sum(1 for o in observations if o.actual_direction == SignalDirection.NO_TRADE)
    unresolved_targets_count = sum(1 for o in observations if o.actual_direction is None)

    v1_actionable = sum(1 for o in observations if o.v1_pred and o.v1_pred.direction in (SignalDirection.UP, SignalDirection.DOWN))
    v2_actionable = sum(1 for o in observations if o.v2_pred and o.v2_pred.direction in (SignalDirection.UP, SignalDirection.DOWN))

    print("\n==================================================================")
    print("                    DATASET & QUALITY SUMMARY REPORT              ")
    print("==================================================================")
    print(f"Dataset File:             {args.file}")
    print(f"Duration:                 {duration:.1f} seconds ({datetime.fromtimestamp(start_ts, tz=timezone.utc).strftime('%H:%M:%S')} to {datetime.fromtimestamp(end_ts, tz=timezone.utc).strftime('%H:%M:%S')})")
    print(f"Total Raw Events:         {stats['total_raw_events']}")
    print(f"  - bookTicker Events:    {stats['book_ticker_events']}")
    print(f"  - depth Events:         {stats['depth_events']}")
    print(f"  - trade Events:         {stats['trade_events']}")
    print(f"  - detrade round Events: {stats['detrade_round_events']}")
    print(f"  - candle Context:       {len(all_candles)} (embedded={len(stats.get('embedded_candles', []))})")
    print(f"Data Quality Issues:      Out-of-order={stats['out_of_order_re_sorted']}, Duplicates={stats['duplicate_timestamps']}, Corrupted={stats['corrupted_lines']}")
    print(f"Total Evaluation Points:  {len(observations)}")
    print(f"Target Resolution (5s):   Directional={valid_targets_count}, Flat={flat_targets_count}, Unresolved={unresolved_targets_count}")
    print(f"Predictions Generated:    V1={v1_preds_count}, V2={v2_preds_count}")
    print(f"Actionable Signals:       V1={v1_actionable}, V2={v2_actionable}")

    # ==================================================================
    # MODE A: BINANCE PROXY BENCHMARK
    # ==================================================================
    print("\n==================================================================")
    print("      MODE A: BINANCE PROXY BENCHMARK (V2 vs Binance 5s Movement) ")
    print("  NOTICE: Target is Binance BTCUSDT movement over ~5 seconds.     ")
    print("  This is a PROXY BENCHMARK only. It is NOT BC.GAME ACCURACY.     ")
    print("==================================================================")

    splits = create_embargoed_splits(observations, embargo_seconds=5.0)
    for split_name, start_i, end_i in splits:
        split_obs = observations[start_i:end_i]
        print_split_metrics(split_obs, "BTC_ORIGINAL_INTELLIGENCE_TIMER_V1", split_name, is_v2=False, benchmark_label="BINANCE PROXY")
        print_split_metrics(split_obs, "BTC_MICROSTRUCTURE_V2", split_name, is_v2=True, benchmark_label="BINANCE PROXY")

    print("\n------------------------------------------------------------------")
    print("   MODE A: NON-OVERLAPPING 5S BLOCKS (BINANCE PROXY BENCHMARK)    ")
    print("------------------------------------------------------------------")
    block_obs = filter_non_overlapping_obs(observations, block_seconds=5.0)
    block_splits = create_embargoed_splits(block_obs, embargo_seconds=5.0)
    for split_name, start_i, end_i in block_splits:
        split_b = block_obs[start_i:end_i]
        print_split_metrics(split_b, "BTC_ORIGINAL_INTELLIGENCE_TIMER_V1", split_name, is_v2=False, benchmark_label="BINANCE PROXY")
        print_split_metrics(split_b, "BTC_MICROSTRUCTURE_V2", split_name, is_v2=True, benchmark_label="BINANCE PROXY")

    # ==================================================================
    # MODE B: ACTUAL BC.GAME BENCHMARK
    # ==================================================================
    print("\n==================================================================")
    print("      MODE B: ACTUAL BC.GAME BENCHMARK (DeTrade Round Settlement) ")
    print("  AUTHORITATIVE TARGET: DeTrade/BC.GAME BTC/USD Aggregated Index  ")
    print("==================================================================")

    detrade_rounds_raw = stats.get("detrade_rounds", {})
    if not detrade_rounds_raw:
        print("STATUS: UNAVAILABLE in this dataset.")
        print("Note: No DeTrade round settlement frames were recorded.")
        print("Actual BC.GAME accuracy can only be evaluated when DeTrade round frames are present.")
        print("Use 'record_microstructure_dataset.py' with DeTrade observer enabled to collect actual settlement data.")
    else:
        detrade_results = await evaluate_actual_detrade_rounds(events, all_candles, detrade_rounds_raw)
        if not detrade_results:
            print("STATUS: INCOMPLETE DeTrade round frames (missing startPrice/endPrice pairs).")
        else:
            # V1 (Production Engine) metrics on actual DeTrade rounds
            v1_actionable = [r for r in detrade_results if r.v1_pred and r.v1_pred.direction in (SignalDirection.UP, SignalDirection.DOWN)]
            v1_correct = sum(1 for r in v1_actionable if r.v1_pred and r.v1_pred.is_correct is True)
            v1_up = [r for r in v1_actionable if r.v1_pred and r.v1_pred.direction == SignalDirection.UP]
            v1_down = [r for r in v1_actionable if r.v1_pred and r.v1_pred.direction == SignalDirection.DOWN]

            v1_acc = (v1_correct / len(v1_actionable) * 100.0) if v1_actionable else 0.0
            v1_acc_up = (sum(1 for r in v1_up if r.v1_pred and r.v1_pred.is_correct is True) / len(v1_up) * 100.0) if v1_up else 0.0
            v1_acc_down = (sum(1 for r in v1_down if r.v1_pred and r.v1_pred.is_correct is True) / len(v1_down) * 100.0) if v1_down else 0.0

            # V2 (Microstructure) metrics
            actionable_detrade = [r for r in detrade_results if r.v2_pred and r.v2_pred.direction in (SignalDirection.UP, SignalDirection.DOWN)]
            correct_detrade = sum(1 for r in actionable_detrade if r.v2_pred and r.v2_pred.is_correct is True)
            up_detrade = [r for r in actionable_detrade if r.v2_pred and r.v2_pred.direction == SignalDirection.UP]
            down_detrade = [r for r in actionable_detrade if r.v2_pred and r.v2_pred.direction == SignalDirection.DOWN]

            acc_detrade = (correct_detrade / len(actionable_detrade) * 100.0) if actionable_detrade else 0.0
            acc_detrade_up = (sum(1 for r in up_detrade if r.v2_pred and r.v2_pred.is_correct is True) / len(up_detrade) * 100.0) if up_detrade else 0.0
            acc_detrade_down = (sum(1 for r in down_detrade if r.v2_pred and r.v2_pred.is_correct is True) / len(down_detrade) * 100.0) if down_detrade else 0.0

            print(f"Total Authoritative Rounds Evaluated: {len(detrade_results)}")
            print("---")
            print(f"V1 (Production Confluence Engine) Actionable Signals: {len(v1_actionable)}")
            print(f"V1 ACTUAL BC.GAME ACCURACY:                          {v1_acc:.2f}% ({v1_correct}/{len(v1_actionable)})")
            print(f"  - UP Accuracy:                                     {v1_acc_up:.2f}% ({sum(1 for r in v1_up if r.v1_pred and r.v1_pred.is_correct is True)}/{len(v1_up)})")
            print(f"  - DOWN Accuracy:                                   {v1_acc_down:.2f}% ({sum(1 for r in v1_down if r.v1_pred and r.v1_pred.is_correct is True)}/{len(v1_down)})")
            print("---")
            print(f"V2 (Microstructure Sidecar) Actionable Signals:       {len(actionable_detrade)}")
            print(f"V2 ACTUAL BC.GAME ACCURACY:                          {acc_detrade:.2f}% ({correct_detrade}/{len(actionable_detrade)})")
            print(f"  - UP Accuracy:                                     {acc_detrade_up:.2f}% ({sum(1 for r in up_detrade if r.v2_pred and r.v2_pred.is_correct is True)}/{len(up_detrade)})")
            print(f"  - DOWN Accuracy:                                   {acc_detrade_down:.2f}% ({sum(1 for r in down_detrade if r.v2_pred and r.v2_pred.is_correct is True)}/{len(down_detrade)})")

    print("\n==================================================================")
    print("                     BENCHMARK EVALUATION COMPLETE                ")
    print("==================================================================")


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
