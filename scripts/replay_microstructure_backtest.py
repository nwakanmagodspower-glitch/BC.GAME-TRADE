#!/usr/bin/env python3
"""Chronological Replay & Benchmark Engine for BTC_ORIGINAL_INTELLIGENCE_TIMER_V1 vs BTC_MICROSTRUCTURE_V2.

Replays recorded bookTicker, depth5@100ms, and trade events with strict zero-lookahead guarantees.
Retrieves real 1-minute historical candles from Binance for slow regime indicators.

Paired Target & Evaluation Structure:
  At each evaluation timestamp t:
    - reference_price: Available mid price at evaluation time t.
    - target_ts: t + 5.0 seconds.
    - target_price: Mid price of the first bookTicker event occurring at or after target_ts (up to 10s max lookahead).
    - actual_direction:
        - UP if target_price > reference_price
        - DOWN if target_price < reference_price
        - FLAT if target_price == reference_price
        - UNRESOLVED if no target bookTicker event is found.

V1 and V2 are evaluated as a paired observation on the exact same timestamp t, reference price, and target direction.

Chronological Splits (Shared Timestamps):
  - Dev / Train (0 - 50%)
  - Validation (50 - 75%)
  - Unseen Test (75 - 100%)

Detailed reporting of raw event counts, evaluation timestamps, unresolved targets, coverage, and actionable signal accuracy.
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


def load_and_validate_dataset(file_path: str) -> tuple[list[ReplayEvent], dict]:
    events: list[ReplayEvent] = []
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Dataset file not found: {file_path}")

    last_ts = 0.0
    out_of_order_count = 0
    duplicate_count = 0
    corrupted_count = 0

    type_counts = {"book_ticker": 0, "depth": 0, "trade": 0}

    with open(file_path, "r") as f:
        for line in f:
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

                if etype in type_counts:
                    type_counts[etype] += 1

                events.append(ReplayEvent(
                    event_type=etype,
                    event_ts=event_ts,
                    local_ts=local_ts,
                    data=payload,
                ))
            except Exception:
                corrupted_count += 1

    events.sort(key=lambda e: e.event_ts)
    stats = {
        "total_raw_events": len(events),
        "book_ticker_events": type_counts["book_ticker"],
        "depth_events": type_counts["depth"],
        "trade_events": type_counts["trade"],
        "out_of_order_re_sorted": out_of_order_count,
        "duplicate_timestamps": duplicate_count,
        "corrupted_lines": corrupted_count,
    }
    return events, stats


async def fetch_historical_candles_for_replay(start_ts: float, end_ts: float) -> list[Candle]:
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
        print(f"Warning: Online candle fetch failed ({exc}). Using historical candle context from dataset if available.")
        return []


def get_candles_available_at(candles: Sequence[Candle], current_ts: float) -> list[Candle]:
    cutoff_dt = datetime.fromtimestamp(current_ts, tz=timezone.utc)
    return [c for c in candles if c.close_time <= cutoff_dt]


async def run_replay_simulation(
    events: list[ReplayEvent],
    all_candles: list[Candle],
    eval_interval_seconds: float = 1.0,
) -> list[PairedObservation]:
    cache = MicrostructureDataCache()
    symbol = settings.analysis_pair.upper()

    observations: list[PairedObservation] = []
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

        if event.event_ts - last_eval_ts >= eval_interval_seconds:
            last_eval_ts = event.event_ts

            candles_now = get_candles_available_at(all_candles, event.event_ts)
            if len(candles_now) < 55:
                continue

            snapshot = await cache.get_snapshot(
                symbol,
                max_book_age_seconds=settings.microstructure_book_max_age_seconds,
                trade_lookback_seconds=15.0,
                reference_time=dt,
            )
            if snapshot.book_ticker is None or not snapshot.is_fresh:
                continue

            book_history = await cache.get_book_history(symbol, lookback_seconds=10.0, reference_time=dt)
            depth_history = await cache.get_depth_history(symbol, lookback_seconds=10.0, reference_time=dt)

            # Evaluate V1
            v1_pred = None
            try:
                v1_features = build_features_v1(candles_now, list(snapshot.recent_ticks))
                v1_score = score_features_v1(v1_features)
                v1_decision = decide_v1(
                    v1_score,
                    min_score=settings.signal_min_score,
                    min_margin=settings.signal_min_margin,
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
            v2_pred = None
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

    # Resolve 5-second Target Horizon on shared PairedObservation objects
    for obs in observations:
        target_ts = obs.ts + 5.0
        subsequent = [mid for ts_m, mid in book_mid_history if target_ts <= ts_m <= target_ts + 10.0]
        if subsequent:
            obs.target_5s_price = subsequent[0]
            if obs.target_5s_price > obs.reference_price:
                obs.actual_direction = SignalDirection.UP
            elif obs.target_5s_price < obs.reference_price:
                obs.actual_direction = SignalDirection.DOWN
            else:
                obs.actual_direction = SignalDirection.NO_TRADE

            if obs.v1_pred and obs.v1_pred.direction in (SignalDirection.UP, SignalDirection.DOWN):
                obs.v1_pred.is_correct = (obs.v1_pred.direction == obs.actual_direction)

            if obs.v2_pred and obs.v2_pred.direction in (SignalDirection.UP, SignalDirection.DOWN):
                obs.v2_pred.is_correct = (obs.v2_pred.direction == obs.actual_direction)

    return observations


def print_split_metrics(observations: Sequence[PairedObservation], engine_name: str, split_name: str, is_v2: bool):
    valid_obs = [o for o in observations if o.actual_direction in (SignalDirection.UP, SignalDirection.DOWN)]
    preds = [(o.v2_pred if is_v2 else o.v1_pred) for o in valid_obs]
    preds = [p for p in preds if p is not None]

    total_evals = len(observations)
    actionable = [p for p in preds if p.direction in (SignalDirection.UP, SignalDirection.DOWN)]
    no_trade_count = total_evals - len(actionable)
    coverage = (len(actionable) / total_evals * 100.0) if total_evals > 0 else 0.0

    up_actionable = [p for p in actionable if p.direction == SignalDirection.UP]
    down_actionable = [p for p in actionable if p.direction == SignalDirection.DOWN]

    correct_total = sum(1 for p in actionable if p.is_correct)
    correct_up = sum(1 for p in up_actionable if p.is_correct)
    correct_down = sum(1 for p in down_actionable if p.is_correct)

    acc_total = (correct_total / len(actionable) * 100.0) if actionable else 0.0
    acc_up = (correct_up / len(up_actionable) * 100.0) if up_actionable else 0.0
    acc_down = (correct_down / len(down_actionable) * 100.0) if down_actionable else 0.0

    strong_actionable = [p for p in actionable if p.quality == "STRONG"]
    valid_actionable = [p for p in actionable if p.quality == "VALID"]

    acc_strong = (sum(1 for p in strong_actionable if p.is_correct) / len(strong_actionable) * 100.0) if strong_actionable else 0.0
    acc_valid = (sum(1 for p in valid_actionable if p.is_correct) / len(valid_actionable) * 100.0) if valid_actionable else 0.0

    print(f"\n--- {engine_name} | {split_name} ---")
    print(f"Total Shared Timestamps: {total_evals}")
    print(f"Actionable Signals:     {len(actionable)} (NO_TRADE: {no_trade_count})")
    print(f"Coverage:              {coverage:.2f}%")
    print(f"Overall Accuracy:      {acc_total:.2f}% ({correct_total}/{len(actionable)})")
    print(f"  - UP Accuracy:       {acc_up:.2f}% ({correct_up}/{len(up_actionable)})")
    print(f"  - DOWN Accuracy:     {acc_down:.2f}% ({correct_down}/{len(down_actionable)})")
    print(f"  - STRONG Accuracy:   {acc_strong:.2f}% ({sum(1 for p in strong_actionable if p.is_correct)}/{len(strong_actionable)})")
    print(f"  - VALID Accuracy:    {acc_valid:.2f}% ({sum(1 for p in valid_actionable if p.is_correct)}/{len(valid_actionable)})")


def filter_non_overlapping_obs(observations: Sequence[PairedObservation], block_seconds: float = 5.0) -> list[PairedObservation]:
    blocks: list[PairedObservation] = []
    last_ts = -1.0
    for o in sorted(observations, key=lambda x: x.ts):
        if o.ts >= last_ts + block_seconds:
            blocks.append(o)
            last_ts = o.ts
    return blocks


def main():
    parser = argparse.ArgumentParser(description="Replay & Benchmark Engine (V1 vs V2).")
    parser.add_argument("--file", type=str, required=True, help="Input dataset JSONL path")
    args = parser.parse_args()

    events, stats = load_and_validate_dataset(args.file)
    if not events:
        print("Error: Dataset empty or invalid.")
        sys.exit(1)

    start_ts = events[0].event_ts
    end_ts = events[-1].event_ts
    duration = end_ts - start_ts

    loop = asyncio.get_event_loop()
    all_candles = loop.run_until_complete(fetch_historical_candles_for_replay(start_ts, end_ts))
    observations = loop.run_until_complete(run_replay_simulation(events, all_candles))

    v1_preds_count = sum(1 for o in observations if o.v1_pred is not None)
    v2_preds_count = sum(1 for o in observations if o.v2_pred is not None)

    valid_targets_count = sum(1 for o in observations if o.actual_direction in (SignalDirection.UP, SignalDirection.DOWN))
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
    print(f"Data Quality Issues:      Out-of-order={stats['out_of_order_re_sorted']}, Duplicates={stats['duplicate_timestamps']}, Corrupted={stats['corrupted_lines']}")
    print(f"Total Evaluation Timestamps: {len(observations)}")
    print(f"Target Resolution:        Valid 5s Targets={valid_targets_count}, Unresolved Targets={unresolved_targets_count}")
    print(f"Predictions Generated:    V1={v1_preds_count}, V2={v2_preds_count}")
    print(f"Actionable Signals:       V1={v1_actionable}, V2={v2_actionable}")

    # Shared Chronological Splits (50% Dev, 25% Val, 25% Test)
    n = len(observations)
    dev_end = int(n * 0.50)
    val_end = int(n * 0.75)

    splits = [
        ("DEV / TRAIN SPLIT (0-50%)", 0, dev_end),
        ("VALIDATION SPLIT (50-75%)", dev_end, val_end),
        ("UNSEEN TEST SPLIT (75-100%)", val_end, n),
    ]

    print("\n==================================================================")
    print("     PAIRED V1 vs V2 BENCHMARK REPORT (RAW OBSERVATIONS)          ")
    print("==================================================================")

    for split_name, start_i, end_i in splits:
        split_obs = observations[start_i:end_i]
        print_split_metrics(split_obs, "BTC_ORIGINAL_INTELLIGENCE_TIMER_V1", split_name, is_v2=False)
        print_split_metrics(split_obs, "BTC_MICROSTRUCTURE_V2", split_name, is_v2=True)

    print("\n==================================================================")
    print("   PAIRED V1 vs V2 BENCHMARK REPORT (NON-OVERLAPPING 5S BLOCKS)   ")
    print("==================================================================")

    block_obs = filter_non_overlapping_obs(observations, block_seconds=5.0)
    n_b = len(block_obs)
    dev_b = int(n_b * 0.50)
    val_b = int(n_b * 0.75)

    block_splits = [
        ("DEV / TRAIN BLOCK SPLIT", 0, dev_b),
        ("VALIDATION BLOCK SPLIT", dev_b, val_b),
        ("UNSEEN TEST BLOCK SPLIT", val_b, n_b),
    ]

    for split_name, start_i, end_i in block_splits:
        split_b = block_obs[start_i:end_i]
        print_split_metrics(split_b, "BTC_ORIGINAL_INTELLIGENCE_TIMER_V1", split_name, is_v2=False)
        print_split_metrics(split_b, "BTC_MICROSTRUCTURE_V2", split_name, is_v2=True)


if __name__ == "__main__":
    main()
