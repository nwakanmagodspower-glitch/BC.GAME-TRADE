from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import websockets

from app.integrations.market_data.base import Candle, MarketDataProvider, MarketTick, ms_to_datetime


class BinanceSpotProvider(MarketDataProvider):
    name = 'BINANCE_SPOT'

    def __init__(self, rest_base_url: str, ws_base_url: str, timeout_seconds: float = 10.0):
        self.rest_base_url = rest_base_url.rstrip('/')
        self.ws_base_url = ws_base_url.rstrip('/')
        self.timeout_seconds = timeout_seconds

    async def fetch_latest_price(self, symbol: str) -> MarketTick:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(f'{self.rest_base_url}/api/v3/ticker/price', params={'symbol': symbol.upper()})
            response.raise_for_status()
            payload = response.json()
        return MarketTick(
            symbol=payload['symbol'],
            price=float(payload['price']),
            quantity=0.0,
            event_time=datetime.now(timezone.utc),
            provider=self.name,
        )

    def _rows_to_candles(self, symbol: str, interval: str, rows: list) -> list[Candle]:
        candles: list[Candle] = []
        for row in rows:
            candles.append(
                Candle(
                    symbol=symbol.upper(),
                    interval=interval,
                    open_time=ms_to_datetime(int(row[0])),
                    close_time=ms_to_datetime(int(row[6])),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                    quote_volume=float(row[7]),
                    trade_count=int(row[8]),
                    taker_buy_base_volume=float(row[9]),
                    taker_buy_quote_volume=float(row[10]),
                    closed=True,
                    provider=self.name,
                )
            )
        return candles

    async def fetch_candles(self, symbol: str, interval: str, limit: int) -> list[Candle]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(
                f'{self.rest_base_url}/api/v3/klines',
                params={'symbol': symbol.upper(), 'interval': interval, 'limit': limit},
            )
            response.raise_for_status()
            rows = response.json()
        return self._rows_to_candles(symbol, interval, rows)

    async def fetch_historical_candles(
        self,
        symbol: str,
        interval: str,
        start_time: datetime,
        end_time: datetime,
        page_limit: int = 1000,
    ) -> list[Candle]:
        """Fetch a bounded historical range without silently using future data."""
        if start_time.tzinfo is None or end_time.tzinfo is None:
            raise ValueError('start_time and end_time must be timezone-aware')
        if end_time <= start_time:
            raise ValueError('end_time must be after start_time')

        start_ms = int(start_time.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000)
        cursor = start_ms
        rows: list = []

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            while cursor < end_ms:
                response = await client.get(
                    f'{self.rest_base_url}/api/v3/klines',
                    params={
                        'symbol': symbol.upper(),
                        'interval': interval,
                        'startTime': cursor,
                        'endTime': end_ms,
                        'limit': page_limit,
                    },
                )
                response.raise_for_status()
                page = response.json()
                if not page:
                    break
                rows.extend(page)
                next_cursor = int(page[-1][0]) + 1
                if next_cursor <= cursor:
                    break
                cursor = next_cursor
                if len(page) < page_limit:
                    break

        # Deduplicate boundary rows while preserving chronological order.
        by_open_time = {int(row[0]): row for row in rows if int(row[0]) < end_ms}
        ordered = [by_open_time[key] for key in sorted(by_open_time)]
        return self._rows_to_candles(symbol, interval, ordered)

    async def stream_ticks(self, symbol: str):
        stream = f'{symbol.lower()}@trade'
        url = f'{self.ws_base_url}/{stream}'
        async with websockets.connect(url, ping_interval=20, ping_timeout=20, close_timeout=10) as websocket:
            async for raw_message in websocket:
                payload = json.loads(raw_message)
                if payload.get('e') != 'trade':
                    continue
                yield MarketTick(
                    symbol=payload['s'],
                    price=float(payload['p']),
                    quantity=float(payload['q']),
                    event_time=ms_to_datetime(int(payload['T'])),
                    provider=self.name,
                    is_buyer_maker=bool(payload['m']),
                )
