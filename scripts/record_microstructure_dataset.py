#!/usr/bin/env python3
"""Record high-frequency Binance BTCUSDT microstructure streams to JSONL for replay evaluation.

Captures:
- bookTicker (best bid/ask price and qty)
- depth5@100ms (top 5 bids and asks levels)
- trade (individual executed market trades)

Includes both provider event timestamp (event_ts) and local receive timestamp (local_ts).

Usage:
    python3 scripts/record_microstructure_dataset.py --duration-seconds 300 --output-file data/sample_microstructure.jsonl
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

from app.core.config import get_settings
from app.integrations.market_data.binance_spot import BinanceSpotProvider

settings = get_settings()


async def record_stream(duration_seconds: int, output_file: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    provider = BinanceSpotProvider(
        rest_base_url=settings.market_data_rest_base_url,
        ws_base_url=settings.market_data_ws_base_url,
    )
    symbol = settings.analysis_pair

    print(f"Starting recording for symbol {symbol} for {duration_seconds}s to {output_file}...")
    start_time = datetime.now(timezone.utc).timestamp()
    count = 0

    async def stream_book():
        nonlocal count
        async for book in provider.stream_book_ticker(symbol):
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
            with open(output_file, 'a') as f:
                f.write(json.dumps(payload) + '\n')
            count += 1
            if datetime.now(timezone.utc).timestamp() - start_time >= duration_seconds:
                break

    async def stream_depth():
        nonlocal count
        async for depth in provider.stream_depth(symbol, levels=5, update_speed_ms=100):
            local_ts = datetime.now(timezone.utc).timestamp()
            payload = {
                'type': 'depth',
                'event_ts': depth.event_time.timestamp(),
                'local_ts': local_ts,
                'bids': [[b.price, b.quantity] for b in depth.bids],
                'asks': [[a.price, a.quantity] for a in depth.asks],
            }
            with open(output_file, 'a') as f:
                f.write(json.dumps(payload) + '\n')
            count += 1
            if datetime.now(timezone.utc).timestamp() - start_time >= duration_seconds:
                break

    async def stream_trades():
        nonlocal count
        async for tick in provider.stream_ticks(symbol):
            local_ts = datetime.now(timezone.utc).timestamp()
            payload = {
                'type': 'trade',
                'event_ts': tick.event_time.timestamp(),
                'local_ts': local_ts,
                'price': tick.price,
                'qty': tick.quantity,
                'is_buyer_maker': tick.is_buyer_maker,
            }
            with open(output_file, 'a') as f:
                f.write(json.dumps(payload) + '\n')
            count += 1
            if datetime.now(timezone.utc).timestamp() - start_time >= duration_seconds:
                break

    try:
        await asyncio.gather(
            asyncio.wait_for(stream_book(), timeout=duration_seconds + 5),
            asyncio.wait_for(stream_depth(), timeout=duration_seconds + 5),
            asyncio.wait_for(stream_trades(), timeout=duration_seconds + 5),
        )
    except asyncio.TimeoutError:
        pass

    print(f"Recording complete. Captured {count} events in {output_file}.")


def main():
    parser = argparse.ArgumentParser(description="Record microstructure stream dataset.")
    parser.add_argument("--duration-seconds", type=int, default=60, help="Duration to record in seconds")
    parser.add_argument("--output-file", type=str, default="data/sample_microstructure.jsonl", help="Output JSONL file path")
    args = parser.parse_args()

    asyncio.run(record_stream(args.duration_seconds, args.output_file))


if __name__ == "__main__":
    main()
