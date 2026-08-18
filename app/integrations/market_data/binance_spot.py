from __future__ import annotations

import json

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
        from datetime import datetime, timezone
        return MarketTick(
            symbol=payload['symbol'],
            price=float(payload['price']),
            quantity=0.0,
            event_time=datetime.now(timezone.utc),
            provider=self.name,
        )

    async def fetch_candles(self, symbol: str, interval: str, limit: int) -> list[Candle]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(
                f'{self.rest_base_url}/api/v3/klines',
                params={'symbol': symbol.upper(), 'interval': interval, 'limit': limit},
            )
            response.raise_for_status()
            rows = response.json()

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
