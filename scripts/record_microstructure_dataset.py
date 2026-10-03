#!/usr/bin/env python3
"""Record high-frequency Binance BTCUSDT microstructure streams and DeTrade round data.

Architecture:
- Single-writer architecture using asyncio.Queue to eliminate concurrent write file contention.
- Bounded exponential backoff reconnection on all stream disruptions.
- Captures:
    * Binance bookTicker (best bid/ask price and quantity)
    * Binance depth5@100ms (top 5 bids and asks levels)
    * Binance trade (individual executed market trades)
    * DeTrade/BC.GAME round frames (authoritative settlement target)
    * 1-minute historical candles (embedded for 100% offline-reproducible replay)
- Preserves both provider event timestamp (event_ts) and local receipt timestamp (local_ts).

Usage:
    python3 scripts/record_microstructure_dataset.py --duration-seconds 300 --output-file data/sample_microstructure.jsonl
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings
from app.integrations.detrade_observer import DeTradeObserver, DeTradeRoundObservation
from app.integrations.market_data.binance_spot import BinanceSpotProvider

settings = get_settings()


async def record_stream(
    duration_seconds: int,
    output_file: str,
    record_detrade: bool = True,
    candle_limit: int = 120,
) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    provider = BinanceSpotProvider(
        rest_base_url=settings.market_data_rest_base_url,
        ws_base_url=settings.market_data_ws_base_url,
    )
    symbol = settings.analysis_pair.upper()

    stop_event = asyncio.Event()
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=10000)

    counts = {
        'book_ticker': 0,
        'depth': 0,
        'trade': 0,
        'detrade_round': 0,
        'candle': 0,
    }

    # --- Dedicated Single-Writer Worker ---
    async def file_writer() -> None:
        write_count = 0
        with open(output_file, 'a', encoding='utf-8') as f:
            while True:
                item = await queue.get()
                if item is None:
                    queue.task_done()
                    break
                f.write(json.dumps(item, separators=(',', ':')) + '\n')
                write_count += 1
                if write_count % 100 == 0:
                    f.flush()
                queue.task_done()
            f.flush()

    writer_task = asyncio.create_task(file_writer(), name='dataset-file-writer')

    # --- Record 1m Candle Context for Offline Replay ---
    print(f"Fetching recent 1m candle context (limit={candle_limit}) for offline replay...")
    try:
        candles = await provider.fetch_candles(symbol, '1m', limit=candle_limit)
        local_ts = datetime.now(timezone.utc).timestamp()
        for candle in candles:
            payload = {
                'type': 'candle',
                'event_ts': candle.close_time.timestamp(),
                'local_ts': local_ts,
                'data': {
                    'open_time': candle.open_time.timestamp(),
                    'close_time': candle.close_time.timestamp(),
                    'open': candle.open,
                    'high': candle.high,
                    'low': candle.low,
                    'close': candle.close,
                    'volume': candle.volume,
                    'quote_volume': candle.quote_volume,
                    'trade_count': candle.trade_count,
                    'taker_buy_base_volume': candle.taker_buy_base_volume,
                    'taker_buy_quote_volume': candle.taker_buy_quote_volume,
                    'closed': candle.closed,
                },
            }
            await queue.put(payload)
            counts['candle'] += 1
        print(f"Recorded {len(candles)} candle frames for offline replay.")
    except Exception as exc:
        print(f"Warning: Failed to fetch initial candles ({exc}). Replay will require online candle fetch.")

    # --- Stream Consumers with Bounded Exponential Backoff ---
    async def stream_book() -> None:
        backoff = 1.0
        max_backoff = 15.0
        while not stop_event.is_set():
            try:
                async for book in provider.stream_book_ticker(symbol):
                    if stop_event.is_set():
                        return
                    backoff = 1.0
                    local_ts = datetime.now(timezone.utc).timestamp()
                    payload = {
                        'type': 'book_ticker',
                        'event_ts': book.event_time.timestamp(),
                        'local_ts': local_ts,
                        'bid': book.best_bid_price,
                        'bid_qty': book.best_bid_qty,
                        'ask': book.best_ask_price,
                        'ask_qty': book.best_ask_qty,
                    }
                    await queue.put(payload)
                    counts['book_ticker'] += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if stop_event.is_set():
                    return
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, max_backoff)

    async def stream_depth() -> None:
        backoff = 1.0
        max_backoff = 15.0
        while not stop_event.is_set():
            try:
                async for depth in provider.stream_depth(symbol, levels=5, update_speed_ms=100):
                    if stop_event.is_set():
                        return
                    backoff = 1.0
                    local_ts = datetime.now(timezone.utc).timestamp()
                    payload = {
                        'type': 'depth',
                        'event_ts': depth.event_time.timestamp(),
                        'local_ts': local_ts,
                        'bids': [[b.price, b.quantity] for b in depth.bids],
                        'asks': [[a.price, a.quantity] for a in depth.asks],
                    }
                    await queue.put(payload)
                    counts['depth'] += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if stop_event.is_set():
                    return
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, max_backoff)

    async def stream_trades() -> None:
        backoff = 1.0
        max_backoff = 15.0
        while not stop_event.is_set():
            try:
                async for tick in provider.stream_ticks(symbol):
                    if stop_event.is_set():
                        return
                    backoff = 1.0
                    local_ts = datetime.now(timezone.utc).timestamp()
                    payload = {
                        'type': 'trade',
                        'event_ts': tick.event_time.timestamp(),
                        'local_ts': local_ts,
                        'price': tick.price,
                        'qty': tick.quantity,
                        'is_buyer_maker': tick.is_buyer_maker,
                    }
                    await queue.put(payload)
                    counts['trade'] += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if stop_event.is_set():
                    return
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, max_backoff)

    # --- DeTrade Round Observer Integration ---
    detrade_observer: DeTradeObserver | None = None
    if record_detrade and (settings.detrade_ws_enabled or settings.detrade_ws_token):
        async def on_detrade_observation(obs: DeTradeRoundObservation) -> None:
            event_ts = (
                obs.price_start_time_ms / 1000.0
                if obs.price_start_time_ms
                else (obs.current_time_ms / 1000.0 if obs.current_time_ms else obs.received_at.timestamp())
            )
            payload = {
                'type': 'detrade_round',
                'event_ts': event_ts,
                'local_ts': obs.received_at.timestamp(),
                'data': {
                    'round_id': obs.round_id,
                    'status': obs.status,
                    'current_time_ms': obs.current_time_ms,
                    'trade_cutoff_time_ms': obs.trade_cutoff_time_ms,
                    'price_start_time_ms': obs.price_start_time_ms,
                    'price_end_time_ms': obs.price_end_time_ms,
                    'start_price': obs.start_price,
                    'end_price': obs.end_price,
                    'previous_round_result': obs.previous_round_result,
                },
            }
            await queue.put(payload)
            counts['detrade_round'] += 1

        async def on_detrade_tick(tick: dict[str, Any]) -> None:
            local_ts = datetime.now(timezone.utc).timestamp()
            t_ms = tick.get('timestamp_ms', 0)
            event_ts = (float(t_ms) / 1000.0) if t_ms > 1e11 else float(t_ms)
            payload = {
                'type': 'detrade_synthetic_tick',
                'event_ts': event_ts,
                'local_ts': local_ts,
                'data': tick,
            }
            await queue.put(payload)
            counts['detrade_tick'] = counts.get('detrade_tick', 0) + 1

        detrade_observer = DeTradeObserver(on_observation=on_detrade_observation, on_tick=on_detrade_tick)
        await detrade_observer.start()
        print("DeTrade synthetic observer connected for real-time tick & settlement recording.")
    else:
        print("DeTrade round recording disabled or token not configured. (Recording Binance streams only)")

    # --- Start Workers ---
    print(f"Starting recording for {symbol} ({duration_seconds}s) -> {output_file}...")
    start_ts = datetime.now(timezone.utc).timestamp()

    tasks = [
        asyncio.create_task(stream_book(), name='stream-book'),
        asyncio.create_task(stream_depth(), name='stream-depth'),
        asyncio.create_task(stream_trades(), name='stream-trades'),
    ]

    try:
        await asyncio.sleep(duration_seconds)
    finally:
        stop_event.set()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        if detrade_observer:
            await detrade_observer.stop()

        # Signal writer to finish and drain queue
        await queue.put(None)
        await writer_task

    total = sum(counts.values())
    print("\n==================================================================")
    print("                    RECORDING COMPLETED                           ")
    print("==================================================================")
    print(f"Output File:           {output_file}")
    print(f"Duration:              {datetime.now(timezone.utc).timestamp() - start_ts:.1f}s")
    print(f"Total Events Captured: {total}")
    print(f"  - bookTicker:        {counts['book_ticker']}")
    print(f"  - depth5:            {counts['depth']}")
    print(f"  - trades:            {counts['trade']}")
    print(f"  - detrade rounds:    {counts['detrade_round']}")
    print(f"  - detrade ticks:     {counts.get('detrade_tick', 0)}")
    print(f"  - candle context:    {counts['candle']}")
    print("==================================================================")


def main() -> None:
    parser = argparse.ArgumentParser(description="Record high-frequency microstructure dataset.")
    parser.add_argument("--duration-seconds", type=int, default=60, help="Duration to record in seconds")
    parser.add_argument("--output-file", type=str, default="data/sample_microstructure.jsonl", help="Output JSONL file path")
    parser.add_argument("--no-detrade", action="store_true", help="Disable DeTrade round observation recording")
    args = parser.parse_args()

    asyncio.run(record_stream(
        duration_seconds=args.duration_seconds,
        output_file=args.output_file,
        record_detrade=not args.no_detrade,
    ))


if __name__ == "__main__":
    main()
