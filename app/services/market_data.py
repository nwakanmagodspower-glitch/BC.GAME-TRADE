from __future__ import annotations

import asyncio
import math
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.integrations.market_data.base import Candle, MarketDataProvider, MarketTick
from app.integrations.market_data.binance_spot import BinanceSpotProvider

settings = get_settings()


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    price: float
    event_time: datetime
    provider: str
    age_seconds: float
    fresh: bool
    last_quantity: float
    is_buyer_maker: bool | None


class MarketDataCache:
    def __init__(self, trade_buffer_size: int | None = None, max_future_skew_seconds: float | None = None):
        buffer_size = trade_buffer_size or settings.market_trade_buffer_size
        self._latest: dict[str, MarketTick] = {}
        self._trades: dict[str, deque[MarketTick]] = defaultdict(lambda: deque(maxlen=buffer_size))
        self._candles: dict[str, list[Candle]] = {}
        self._candles_provider_time: dict[str, datetime] = {}
        self._lock = asyncio.Lock()
        self.max_future_skew_seconds = settings.market_data_future_skew_seconds if max_future_skew_seconds is None else max_future_skew_seconds

    async def set_tick(self, tick: MarketTick) -> None:
        if not math.isfinite(tick.price) or tick.price <= 0:
            raise ValueError('market tick price must be finite and positive')
        if not math.isfinite(tick.quantity) or tick.quantity < 0:
            raise ValueError('market tick quantity must be finite and non-negative')
        event_time = tick.event_time
        if event_time.tzinfo is None:
            raise ValueError('market tick event_time must be timezone-aware')
        if event_time > datetime.now(timezone.utc) + timedelta(seconds=self.max_future_skew_seconds):
            raise ValueError('market tick event_time is too far in the future')
        symbol = tick.symbol.upper()
        async with self._lock:
            self._latest[symbol] = tick
            if tick.quantity > 0:
                self._trades[symbol].append(tick)

    async def set_candles(self, symbol: str, candles: list[Candle]) -> None:
        if not candles:
            raise ValueError('candle cache cannot be populated with an empty series')
        now = datetime.now(timezone.utc)
        provider_times: list[datetime] = []
        for candle in candles:
            if candle.open_time.tzinfo is None or candle.close_time.tzinfo is None:
                raise ValueError('candle timestamps must be timezone-aware')
            if candle.open_time > now + timedelta(seconds=self.max_future_skew_seconds):
                raise ValueError('candle open_time is too far in the future')
            provider_times.append(candle.open_time.astimezone(timezone.utc))
        provider_time = max(provider_times)
        async with self._lock:
            self._candles[symbol.upper()] = list(candles)
            self._candles_provider_time[symbol.upper()] = provider_time

    async def get_candles(self, symbol: str, max_age_seconds: int | None = None) -> list[Candle] | None:
        async with self._lock:
            candles = self._candles.get(symbol.upper())
            provider_time = self._candles_provider_time.get(symbol.upper())
        if candles and max_age_seconds is not None:
            if provider_time is None or (datetime.now(timezone.utc) - provider_time).total_seconds() > max_age_seconds:
                return None
        return list(candles) if candles else None

    async def get_candle_age_seconds(self, symbol: str) -> float | None:
        async with self._lock:
            provider_time = self._candles_provider_time.get(symbol.upper())
        if provider_time is None:
            return None
        return max(0.0, (datetime.now(timezone.utc) - provider_time).total_seconds())

    async def get_snapshot(self, symbol: str, max_age_seconds: int) -> MarketSnapshot | None:
        async with self._lock:
            tick = self._latest.get(symbol.upper())
        if tick is None:
            return None
        now = datetime.now(timezone.utc)
        age = max(0.0, (now - tick.event_time).total_seconds())
        return MarketSnapshot(
            symbol=tick.symbol,
            price=tick.price,
            event_time=tick.event_time,
            provider=tick.provider,
            age_seconds=age,
            fresh=age <= max_age_seconds,
            last_quantity=tick.quantity,
            is_buyer_maker=tick.is_buyer_maker,
        )

    async def get_recent_ticks(self, symbol: str, lookback_seconds: int) -> list[MarketTick]:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=lookback_seconds)
        async with self._lock:
            ticks = list(self._trades.get(symbol.upper(), ()))
        return [tick for tick in ticks if tick.event_time >= cutoff]

    async def get_trade_window_metrics(self, symbol: str, lookback_seconds: int) -> tuple[int, float]:
        ticks = await self.get_recent_ticks(symbol, lookback_seconds)
        if len(ticks) < 2:
            return len(ticks), 0.0
        span = (max(t.event_time for t in ticks) - min(t.event_time for t in ticks)).total_seconds()
        return len(ticks), max(0.0, span)


class MarketDataService:
    def __init__(self, provider: MarketDataProvider, cache: MarketDataCache):
        self.provider = provider
        self.cache = cache
        self._task: asyncio.Task | None = None
        self._candle_task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.last_error: str | None = None
        self.candle_last_error: str | None = None
        self.connected = False

    async def bootstrap(self, symbol: str) -> None:
        tick, candles = await asyncio.gather(
            self.provider.fetch_latest_price(symbol),
            self.provider.fetch_candles(symbol, '1m', settings.market_data_kline_limit),
        )
        await self.cache.set_tick(tick)
        await self.cache.set_candles(symbol, candles)

    async def fetch_candles(self, symbol: str, interval: str, limit: int | None = None) -> list[Candle]:
        return await self.provider.fetch_candles(symbol, interval, limit or settings.market_data_kline_limit)

    async def get_cached_candles(self, symbol: str) -> list[Candle] | None:
        return await self.cache.get_candles(symbol, settings.market_candle_max_age_seconds)

    async def start(self, symbol: str) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        try:
            await self.bootstrap(symbol)
            self.last_error = None
            self.candle_last_error = None
        except Exception as exc:
            error = f'{type(exc).__name__}: {exc}'
            self.last_error = error
            self.candle_last_error = error
        self._task = asyncio.create_task(self._run_ticks(symbol), name=f'market-data-{symbol.lower()}')
        self._candle_task = asyncio.create_task(self._run_candles(symbol), name=f'candle-cache-{symbol.lower()}')

    async def stop(self) -> None:
        self._stop.set()
        for task in (self._task, self._candle_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self.connected = False

    async def _run_ticks(self, symbol: str) -> None:
        while not self._stop.is_set():
            try:
                self.connected = True
                self.last_error = None
                async for tick in self.provider.stream_ticks(symbol):
                    if self._stop.is_set():
                        return
                    await self.cache.set_tick(tick)
                self.connected = False
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.connected = False
                self.last_error = f'{type(exc).__name__}: {exc}'
                await asyncio.sleep(settings.market_data_reconnect_seconds)

    async def _run_candles(self, symbol: str) -> None:
        while not self._stop.is_set():
            try:
                candles = await self.provider.fetch_candles(symbol, '1m', settings.market_data_kline_limit)
                await self.cache.set_candles(symbol, candles)
                self.candle_last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.candle_last_error = f'{type(exc).__name__}: {exc}'
            await asyncio.sleep(settings.market_candle_refresh_seconds)


def build_market_data_service() -> MarketDataService:
    provider_name = settings.market_data_provider.upper()
    if provider_name != 'BINANCE_SPOT':
        raise ValueError(f'Unsupported market data provider: {provider_name}')
    provider = BinanceSpotProvider(
        rest_base_url=settings.market_data_rest_base_url,
        ws_base_url=settings.market_data_ws_base_url,
        max_response_bytes=settings.market_data_rest_max_response_bytes,
    )
    return MarketDataService(provider=provider, cache=MarketDataCache(settings.market_trade_buffer_size))


market_data_service = build_market_data_service()
