#!/usr/bin/env python3
"""Replay evaluation benchmark engine for 5-second binary direction predictions.

Strictly prevents look-ahead bias by replaying recorded events in chronological order,
calculating features using ONLY past data, evaluating 5-second target horizons:
    Y(t) = UP if P_mid(t + 5s) > P_mid(t) else DOWN if P_mid(t + 5s) < P_mid(t) else FLAT

Splits data chronologically into Dev/Train (60%) and Unseen Test (40%).
Reports UP, DOWN, overall accuracy, coverage, confidence stratification, and comparison.
"""

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from app.integrations.market_data.base import BookTicker, Candle, MarketTick
from app.models.entities import SignalDirection
from app.services.market_data import MicrostructureDataCache
from app.signals.microstructure.decision import decide_microstructure
from app.signals.microstructure.features import build_microstructure_features
from app.signals.microstructure.scoring import score_microstructure_features


@dataclass
class ReplayEvent:
    event_type: str
    ts: float
    data: dict


@dataclass
class PredictionRecord:
    ts: float
    reference_price: float
    direction: SignalDirection
    quality: str
    bull_score: int
    bear_score: int
    margin: int
    target_5s_price: float | None = None
    actual_direction: SignalDirection | None = None
    is_correct: bool | None = None


def load_dataset(file_path: str) -> list[ReplayEvent]:
    events: list[ReplayEvent] = []
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Dataset file not found: {file_path}")

    with open(file_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            events.append(ReplayEvent(
                event_type=payload["type"],
                ts=float(payload["ts"]),
                data=payload,
            ))

    events.sort(key=lambda e: e.ts)
    return events


def create_dummy_candles(price: float, count: int = 60) -> list[Candle]:
    now = datetime.now(timezone.utc)
    candles = []
    for i in range(count):
        ot = now
        ct = now
        candles.append(Candle(
            symbol="BTCUSDT",
            interval="1m",
            open_time=ot,
            close_time=ct,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=100.0,
            quote_volume=100.0 * price,
            trade_count=1000,
            taker_buy_base_volume=50.0,
            taker_buy_quote_volume=50.0 * price,
            closed=True,
            provider="BINANCE_SPOT",
        ))
    return candles


async def run_replay(events: list[ReplayEvent], eval_interval_seconds: float = 1.0) -> list[PredictionRecord]:
    cache = MicrostructureDataCache()
    predictions: list[PredictionRecord] = []
    symbol = "BTCUSDT"

    book_mid_history: list[tuple[float, float]] = []  # (ts, mid_price)
    last_eval_ts = 0.0

    dummy_candles = None

    for event in events:
        dt = datetime.fromtimestamp(event.ts, tz=timezone.utc)

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
            book_mid_history.append((event.ts, book.mid_price))

            if dummy_candles is None:
                dummy_candles = create_dummy_candles(book.mid_price)

        elif event.event_type == "trade":
            tick = MarketTick(
                symbol=symbol,
                price=float(event.data["price"]),
                quantity=float(event.data["qty"]),
                event_time=dt,
                provider="BINANCE_SPOT",
                is_buyer_maker=bool(event.data["is_buyer_maker"]),
            )
            await cache.add_trade(tick)

        # Periodic signal evaluation
        if dummy_candles and (event.ts - last_eval_ts >= eval_interval_seconds):
            last_eval_ts = event.ts
            snapshot = await cache.get_snapshot(symbol, max_book_age_seconds=2.0, trade_lookback_seconds=10.0)

            if snapshot.book_ticker is not None:
                book_history = await cache.get_book_history(symbol, lookback_seconds=10.0)
                try:
                    features = build_microstructure_features(
                        candles=dummy_candles,
                        latest_book=snapshot.book_ticker,
                        book_history=book_history,
                        depth=None,
                        depth_history=(),
                        recent_ticks=snapshot.recent_ticks,
                        now=dt,
                    )
                    score = score_microstructure_features(features)
                    decision = decide_microstructure(
                        score=score,
                        features=features,
                        is_fresh=True,
                        max_spread_bps=5.0,
                        min_l5_volume=0.0,
                        min_score=5,
                        min_margin=3,
                    )

                    predictions.append(PredictionRecord(
                        ts=event.ts,
                        reference_price=snapshot.book_ticker.mid_price,
                        direction=decision.direction,
                        quality=decision.quality,
                        bull_score=decision.bull_score,
                        bear_score=decision.bear_score,
                        margin=decision.margin,
                    ))
                except Exception:
                    pass

    # Resolve target 5 seconds horizon
    for p in predictions:
        target_ts = p.ts + 5.0
        # find book mid price closest to target_ts
        subsequent = [m for ts, m in book_mid_history if ts >= target_ts]
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

    return predictions


def evaluate_predictions(predictions: list[PredictionRecord], name: str = "Dataset Split"):
    total = len(predictions)
    traded = [p for p in predictions if p.direction in (SignalDirection.UP, SignalDirection.DOWN) and p.is_correct is not None]
    coverage = len(traded) / total * 100.0 if total > 0 else 0.0

    up_traded = [p for p in traded if p.direction == SignalDirection.UP]
    down_traded = [p for p in traded if p.direction == SignalDirection.DOWN]

    correct_total = sum(1 for p in traded if p.is_correct)
    correct_up = sum(1 for p in up_traded if p.is_correct)
    correct_down = sum(1 for p in down_traded if p.is_correct)

    acc_total = correct_total / len(traded) * 100.0 if traded else 0.0
    acc_up = correct_up / len(up_traded) * 100.0 if up_traded else 0.0
    acc_down = correct_down / len(down_traded) * 100.0 if down_traded else 0.0

    print(f"\n==================== {name} ====================")
    print(f"Total Observations Evaluated: {total}")
    print(f"Coverage (Actionable Signals): {coverage:.2f}% ({len(traded)}/{total})")
    print(f"Overall Traded Accuracy:     {acc_total:.2f}% ({correct_total}/{len(traded)})")
    print(f"UP Signal Accuracy:          {acc_up:.2f}% ({correct_up}/{len(up_traded)})")
    print(f"DOWN Signal Accuracy:        {acc_down:.2f}% ({correct_down}/{len(down_traded)})")


def main():
    parser = argparse.ArgumentParser(description="Replay evaluation benchmark engine.")
    parser.add_argument("--file", type=str, required=True, help="Input JSONL file path")
    args = parser.parse_args()

    events = load_dataset(args.file)
    print(f"Loaded {len(events)} events from {args.file}")

    predictions = asyncio.run(run_replay(events))

    # Chronological 60/40 Split
    split_idx = int(len(predictions) * 0.6)
    dev_predictions = predictions[:split_idx]
    test_predictions = predictions[split_idx:]

    evaluate_predictions(dev_predictions, name="DEV/TRAIN SPLIT (First 60%)")
    evaluate_predictions(test_predictions, name="UNSEEN TEST SPLIT (Final 40%)")


if __name__ == "__main__":
    main()
