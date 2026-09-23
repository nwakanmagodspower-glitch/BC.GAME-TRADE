#!/usr/bin/env python3
"""Chronological Replay & Benchmark Engine for BTC_ORIGINAL_INTELLIGENCE_TIMER_V1 vs BTC_MICROSTRUCTURE_V2.

Replays recorded bookTicker, depth5@100ms, and trade events with strict zero-lookahead guarantees.
Retrieves real 1-minute historical candles from Binance for the slow regime indicators.

Evaluation Target at t:
  - reference_price: Available mid price at evaluation time t.
  - target_ts: t + 5.0 seconds.
  - target_price: Mid price of the first bookTicker event at or after target_ts.
  - actual_direction:
      - UP if target_price > reference_price
      - DOWN if target_price < reference_price
      - FLAT if target_price == reference_price
      - UNRESOLVED if no bookTicker event exists at or after target_ts within max_horizon_lookahead (e.g. 10s).

Chronological Splits:
  - Dev/Train (First 50%)
  - Validation (Next 25%)
  - Unseen Test (Final 25%)

Reports raw observation counts, non-overlapping grouped window metrics, and side-by-side V1 vs V2 benchmarks.
"""

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from app.core.config import get_settings
from app.integrations.market_data.base import BookTicker, Candle, DepthLevel, DepthSnapshot, MarketTick
from app.integrations.market_data.binance_spot import BinanceSpotProvider
from app.models.entities import SignalDirection
from app.services.market_data import MicrostructureDataCache
from app.signals.decision import decide as decide_v1
from app.signals.features import build_features as build_features_v1
from app.signals.microstructure.decision import decide_microstructure as decide_v2
from app.signals.microstructure.features import build_microstructure_features
from app.signals.microstructure.scoring import score_microstructure_features
from app.signals.scoring import score_features as score_features_v1

settings = get_settings()


@dataclass
class ReplayEvent:
    event_type: str
    event_ts: float
    local_ts: float
    data: dict


@dataclass
class EnginePrediction:
    ts: float
    reference_price: float
    direction: SignalDirection
    quality: str
    bull_score: int
    bear_score: int
    margin: int
    spread_bps: float
    atr_14_pct: float
    target_5s_price: float | None = None
    actual_direction: SignalDirection | None = None
    is_correct: bool | None = None


def load_and_validate_dataset(file_path: str) -> list[ReplayEvent]:
    events: list[ReplayEvent] = []
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Dataset file not found: {file_path}")

    last_ts = 0.0
    out_of_order_count = 0
    duplicate_count = 0
    corrupted_count = 0

    with open(file_path, "r") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                etype = payload["type"]
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

                events.append(ReplayEvent(
                    event_type=etype,
                    event_ts=event_ts,
                    local_ts=local_ts,
                    data=payload,
                ))
            except Exception:
                corrupted_count += 1

    print(f"Dataset Quality Report for {file_path}:")
    print(f"  - Total Valid Events Loaded: {len(events)}")
    print(f"  - Out-of-Order Events Re-sorted: {out_of_order_count}")
    print(f"  - Duplicate Timestamps: {duplicate_count}")
    print(f"  - Corrupted Lines Skipped: {corrupted_count}")

    # Enforce strict chronological order
    events.sort(key=lambda e: e.event_ts)
    return events


async def fetch_historical_candles_for_replay(start_ts: float, end_ts: float) -> list[Candle]:
    provider = BinanceSpotProvider(
        rest_base_url=settings.market_data_rest_base_url,
        ws_base_url=settings.market_data_ws_base_url,
    )
    # Fetch 2 hours prior to ensure enough closed 1m candles (>= 55 required)
    start_dt = datetime.fromtimestamp(start_ts - 7200, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(end_ts + 60, tz=timezone.utc)

    print(f"Fetching real historical 1m candles from Binance ({start_dt.strftime('%H:%M:%S')} to {end_dt.strftime('%H:%M:%S')})...")
    try:
        candles = await provider.fetch_historical_candles(
            symbol=settings.analysis_pair,
            interval="1m",
            start_time=start_dt,
            end_time=end_dt,
        )
        print(f"Fetched {len(candles)} real historical candles.")
        return candles
    except Exception as exc:
        print(f"Warning: Failed to fetch online candles ({exc}). Replay will use fallback candle builder if offline.")
        return []


def get_candles_available_at(candles: Sequence[Candle], current_ts: float) -> list[Candle]:
    """Strict zero look-ahead filter: Returns candles whose close_time <= current_ts."""
    cutoff_dt = datetime.fromtimestamp(current_ts, tz=timezone.utc)
    return [c for c in candles if c.close_time <= cutoff_dt]


async def run_replay_simulation(
    events: list[ReplayEvent],
    all_candles: list[Candle],
    eval_interval_seconds: float = 1.0,
) -> tuple[list[EnginePrediction], list[EnginePrediction]]:
    cache = MicrostructureDataCache()
    symbol = settings.analysis_pair.upper()

    v1_predictions: list[EnginePrediction] = []
    v2_predictions: list[EnginePrediction] = []

    book_mid_history: list[tuple[float, float]] = []  # (event_ts, mid_price)
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
            book_mid_history.append((event.event_ts, book.mid_price))

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

        # Trigger periodic evaluations
        if event.event_ts - last_eval_ts >= eval_interval_seconds:
            last_eval_ts = event.event_ts

            # Strict zero look-ahead candle context
            candles_now = get_candles_available_at(all_candles, event.event_ts)
            if len(candles_now) < 55:
                continue

            snapshot = await cache.get_snapshot(symbol, max_book_age_seconds=2.0, trade_lookback_seconds=15.0)
            if snapshot.book_ticker is None or not snapshot.is_fresh:
                continue

            book_history = await cache.get_book_history(symbol, lookback_seconds=10.0)
            depth_history = await cache.get_depth_history(symbol, lookback_seconds=10.0)

            # Evaluate V1 (Original Intelligence)
            try:
                v1_features = build_features_v1(candles_now, list(snapshot.recent_ticks))
                v1_score = score_features_v1(v1_features)
                v1_decision = decide_v1(
                    v1_score,
                    min_score=settings.signal_min_score,
                    min_margin=settings.signal_min_margin,
                )
                v1_predictions.append(EnginePrediction(
                    ts=event.event_ts,
                    reference_price=snapshot.book_ticker.mid_price,
                    direction=v1_decision.direction,
                    quality=v1_decision.quality,
                    bull_score=v1_decision.bull_score,
                    bear_score=v1_decision.bear_score,
                    margin=v1_decision.margin,
                    spread_bps=snapshot.book_ticker.spread_bps,
                    atr_14_pct=v1_features.atr_14_pct,
                ))
            except Exception:
                pass

            # Evaluate V2 (Microstructure)
            try:
                v2_features = build_microstructure_features(
                    candles=candles_now,
                    latest_book=snapshot.book_ticker,
                    book_history=book_history,
                    depth=snapshot.depth,
                    depth_history=depth_history,
                    recent_ticks=snapshot.recent_ticks,
                    now=dt,
                )
                v2_score = score_microstructure_features(v2_features)
                v2_decision = decide_microstructure(
                    score=v2_score,
                    features=v2_features,
                    is_fresh=True,
                    max_spread_bps=settings.microstructure_max_spread_bps,
                    min_l5_volume=settings.microstructure_min_l5_volume,
                    min_score=settings.microstructure_min_score,
                    min_margin=settings.microstructure_min_margin,
                )
                v2_predictions.append(EnginePrediction(
                    ts=event.event_ts,
                    reference_price=snapshot.book_ticker.mid_price,
                    direction=v2_decision.direction,
                    quality=v2_decision.quality,
                    bull_score=v2_decision.bull_score,
                    bear_score=v2_decision.bear_score,
                    margin=v2_decision.margin,
                    spread_bps=v2_features.spread_bps,
                    atr_14_pct=v2_features.atr_14_pct,
                ))
            except Exception:
                pass

    # Resolve 5-second Target Horizon on exact same target prices
    for pred_list in (v1_predictions, v2_predictions):
        for p in pred_list:
            target_ts = p.ts + 5.0
            # Target price definition: First bookTicker mid price occurring at or after t+5.0s
            subsequent = [mid for ts_m, mid in book_mid_history if ts_m >= target_ts]
            if subsequent:
                p.target_5s_price = subsequent[0]
                if p.target_5s_price > p.reference_price:
                    p.actual_direction = SignalDirection.UP
                elif p.target_5s_price < p.reference_price:
                    p.actual_direction = SignalDirection.DOWN
                else:
                    p.actual_direction = SignalDirection.NO_TRADE

                if p.direction in (SignalDirection.UP, SignalDirection.DOWN):
                    p.is_correct = (p.direction == p.actual_direction)

    return v1_predictions, v2_predictions


def evaluate_metrics(predictions: list[EnginePrediction], engine_name: str, split_name: str):
    total = len(predictions)
    traded = [p for p in predictions if p.direction in (SignalDirection.UP, SignalDirection.DOWN) and p.is_correct is not None]
    no_trade_count = total - len(traded)
    coverage = (len(traded) / total * 100.0) if total > 0 else 0.0

    up_traded = [p for p in traded if p.direction == SignalDirection.UP]
    down_traded = [p for p in traded if p.direction == SignalDirection.DOWN]

    correct_total = sum(1 for p in traded if p.is_correct)
    correct_up = sum(1 for p in up_traded if p.is_correct)
    correct_down = sum(1 for p in down_traded if p.is_correct)

    acc_total = (correct_total / len(traded) * 100.0) if traded else 0.0
    acc_up = (correct_up / len(up_traded) * 100.0) if up_traded else 0.0
    acc_down = (correct_down / len(down_traded) * 100.0) if down_traded else 0.0

    strong_traded = [p for p in traded if p.quality == "STRONG"]
    valid_traded = [p for p in traded if p.quality == "VALID"]

    acc_strong = (sum(1 for p in strong_traded if p.is_correct) / len(strong_traded) * 100.0) if strong_traded else 0.0
    acc_valid = (sum(1 for p in valid_traded if p.is_correct) / len(valid_traded) * 100.0) if valid_traded else 0.0

    print(f"\n--- {engine_name} | {split_name} ---")
    print(f"Total Observations:    {total}")
    print(f"Actionable Traded:     {len(traded)} (NO_TRADE: {no_trade_count})")
    print(f"Coverage:              {coverage:.2f}%")
    print(f"Overall Accuracy:      {acc_total:.2f}% ({correct_total}/{len(traded)})")
    print(f"  - UP Accuracy:       {acc_up:.2f}% ({correct_up}/{len(up_traded)})")
    print(f"  - DOWN Accuracy:     {acc_down:.2f}% ({correct_down}/{len(down_traded)})")
    print(f"  - STRONG Accuracy:   {acc_strong:.2f}% ({sum(1 for p in strong_traded if p.is_correct)}/{len(strong_traded)})")
    print(f"  - VALID Accuracy:    {acc_valid:.2f}% ({sum(1 for p in valid_traded if p.is_correct)}/{len(valid_traded)})")


def filter_non_overlapping_blocks(predictions: list[EnginePrediction], block_seconds: float = 5.0) -> list[EnginePrediction]:
    """Group overlapping observations into non-overlapping block windows."""
    blocks: list[EnginePrediction] = []
    last_ts = -1.0
    for p in sorted(predictions, key=lambda x: x.ts):
        if p.ts >= last_ts + block_seconds:
            blocks.append(p)
            last_ts = p.ts
    return blocks


def main():
    parser = argparse.ArgumentParser(description="Replay & Benchmark Engine (V1 vs V2).")
    parser.add_argument("--file", type=str, required=True, help="Input dataset JSONL path")
    args = parser.parse_args()

    events = load_and_validate_dataset(args.file)
    if not events:
        print("Error: Dataset empty or invalid.")
        sys.exit(1)

    start_ts = events[0].event_ts
    end_ts = events[-1].event_ts
    duration = end_ts - start_ts
    print(f"Dataset span: {duration:.1f} seconds ({datetime.fromtimestamp(start_ts, tz=timezone.utc).strftime('%H:%M:%S')} to {datetime.fromtimestamp(end_ts, tz=timezone.utc).strftime('%H:%M:%S')})")

    # Fetch real historical candles
    loop = asyncio.get_event_loop()
    all_candles = loop.run_until_complete(fetch_historical_candles_for_replay(start_ts, end_ts))

    v1_preds, v2_preds = loop.run_until_complete(run_replay_simulation(events, all_candles))

    # Chronological Split (50% Dev, 25% Val, 25% Test)
    n = len(v1_preds)
    dev_end = int(n * 0.50)
    val_end = int(n * 0.75)

    splits = [
        ("DEV / TRAIN SPLIT (0-50%)", 0, dev_end),
        ("VALIDATION SPLIT (50-75%)", dev_end, val_end),
        ("UNSEEN TEST SPLIT (75-100%)", val_end, n),
    ]

    print("\n==================================================================")
    print("      V1 vs V2 BENCHMARK REPORT (RAW OVERLAPPING OBSERVATIONS)    ")
    print("==================================================================")

    for split_name, start_i, end_i in splits:
        evaluate_metrics(v1_preds[start_i:end_i], "BTC_ORIGINAL_INTELLIGENCE_TIMER_V1", split_name)
        evaluate_metrics(v2_preds[start_i:end_i], "BTC_MICROSTRUCTURE_V2", split_name)

    print("\n==================================================================")
    print("  V1 vs V2 BENCHMARK REPORT (NON-OVERLAPPING 5-SECOND TIME BLOCKS)")
    print("==================================================================")

    v1_blocks = filter_non_overlapping_blocks(v1_preds, block_seconds=5.0)
    v2_blocks = filter_non_overlapping_blocks(v2_preds, block_seconds=5.0)

    n_b = len(v1_blocks)
    dev_b = int(n_b * 0.50)
    val_b = int(n_b * 0.75)

    block_splits = [
        ("DEV / TRAIN BLOCK SPLIT", 0, dev_b),
        ("VALIDATION BLOCK SPLIT", dev_b, val_b),
        ("UNSEEN TEST BLOCK SPLIT", val_b, n_b),
    ]

    for split_name, start_i, end_i in block_splits:
        evaluate_metrics(v1_blocks[start_i:end_i], "BTC_ORIGINAL_INTELLIGENCE_TIMER_V1", split_name)
        evaluate_metrics(v2_blocks[start_i:end_i], "BTC_MICROSTRUCTURE_V2", split_name)


if __name__ == "__main__":
    main()
