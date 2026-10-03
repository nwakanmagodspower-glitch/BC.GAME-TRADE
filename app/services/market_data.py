from __future__ import annotations

import asyncio
import math
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.integrations.market_data.base import BookTicker, Candle, DepthLevel, DepthSnapshot, MarketDataProvider, MarketTick
from app.integrations.market_data.binance_spot import BinanceSpotProvider
from app.integrations.market_data.five_second_bar import FiveSecondBar, FiveSecondBarAggregator

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
        self._candles_received_monotonic: dict[str, float] = {}
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
            current_latest = self._latest.get(symbol)
            if (
                settings.detrade_use_synthetic_feed
                and current_latest is not None
                and current_latest.provider == 'DETRADE_SYNTHETIC'
                and tick.provider != 'DETRADE_SYNTHETIC'
            ):
                age = (datetime.now(timezone.utc) - current_latest.event_time).total_seconds()
                if 0 <= age <= settings.market_data_max_age_seconds:
                    if tick.quantity > 0:
                        self._trades[symbol].append(tick)
                    return
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
            # A completed one-minute candle is current through its close, not
            # merely through its open. Aging it from open_time creates a false
            # stale window at every minute boundary when Binance returns only
            # completed rows. For an in-progress candle, its open is the latest
            # authoritative provider timestamp available.
            provider_reference = candle.close_time if candle.closed else candle.open_time
            provider_times.append(provider_reference.astimezone(timezone.utc))
        provider_time = max(provider_times)
        async with self._lock:
            self._candles[symbol.upper()] = list(candles)
            self._candles_provider_time[symbol.upper()] = provider_time
            self._candles_received_monotonic[symbol.upper()] = asyncio.get_running_loop().time()

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

    async def get_candle_refresh_age_seconds(self, symbol: str) -> float | None:
        """Age of the last successful cache refresh, independent of candle boundaries."""
        async with self._lock:
            received = self._candles_received_monotonic.get(symbol.upper())
        if received is None:
            return None
        return max(0.0, asyncio.get_running_loop().time() - received)

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
        self.book_ticker_last_error: str | None = None
        self.depth_last_error: str | None = None
        self.connected = False
        self._book_ticker_task: asyncio.Task | None = None
        self._depth_task: asyncio.Task | None = None
        self.microstructure_cache = MicrostructureDataCache()

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
        if not settings.detrade_use_synthetic_feed:
            self._book_ticker_task = asyncio.create_task(self._run_book_ticker(symbol), name=f'book-ticker-{symbol.lower()}')
            self._depth_task = asyncio.create_task(self._run_depth(symbol), name=f'depth-{symbol.lower()}')

    async def stop(self) -> None:
        self._stop.set()
        for task in (self._task, self._candle_task, self._book_ticker_task, self._depth_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self.connected = False

    async def _run_ticks(self, symbol: str) -> None:
        backoff = float(settings.market_data_reconnect_seconds)
        max_backoff = 30.0
        while not self._stop.is_set():
            try:
                self.connected = True
                self.last_error = None
                async for tick in self.provider.stream_ticks(symbol):
                    if self._stop.is_set():
                        return
                    backoff = float(settings.market_data_reconnect_seconds)
                    await self.cache.set_tick(tick)
                    await self.microstructure_cache.add_trade(tick)
                self.connected = False
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.connected = False
                self.last_error = f'{type(exc).__name__}: {exc}'
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, max_backoff)

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

    async def _run_book_ticker(self, symbol: str) -> None:
        backoff = float(settings.market_data_reconnect_seconds)
        max_backoff = 30.0
        while not self._stop.is_set():
            try:
                self.book_ticker_last_error = None
                async for book in self.provider.stream_book_ticker(symbol):
                    if self._stop.is_set():
                        return
                    backoff = float(settings.market_data_reconnect_seconds)
                    await self.microstructure_cache.add_book_ticker(book)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.book_ticker_last_error = f'{type(exc).__name__}: {exc}'
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, max_backoff)

    async def _run_depth(self, symbol: str) -> None:
        backoff = float(settings.market_data_reconnect_seconds)
        max_backoff = 30.0
        while not self._stop.is_set():
            try:
                self.depth_last_error = None
                async for depth in self.provider.stream_depth(symbol, levels=5, update_speed_ms=100):
                    if self._stop.is_set():
                        return
                    backoff = float(settings.market_data_reconnect_seconds)
                    await self.microstructure_cache.add_depth_snapshot(depth)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.depth_last_error = f'{type(exc).__name__}: {exc}'
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, max_backoff)



@dataclass(frozen=True)
class MicrostructureSnapshot:
    symbol: str
    book_ticker: BookTicker | None
    depth: DepthSnapshot | None
    recent_ticks: tuple[MarketTick, ...]
    book_ticker_age_seconds: float | None
    depth_age_seconds: float | None
    is_fresh: bool
    last_5s_bar: FiveSecondBar | None = None
    bars_5s: tuple[FiveSecondBar, ...] = ()
    bar_metrics_5s: dict[str, Any] | None = None


class MicrostructureDataCache:
    """Thread-safe (asyncio.Lock protected) rolling buffer cache for high-frequency microstructure streams."""

    def __init__(self, book_history_size: int = 2000, depth_history_size: int = 500, trade_history_size: int = 10000):
        self._book_tickers: dict[str, deque[BookTicker]] = defaultdict(lambda: deque(maxlen=book_history_size))
        self._depth_snapshots: dict[str, deque[DepthSnapshot]] = defaultdict(lambda: deque(maxlen=depth_history_size))
        self._trades: dict[str, deque[MarketTick]] = defaultdict(lambda: deque(maxlen=trade_history_size))
        self._bar_aggregators: dict[str, FiveSecondBarAggregator] = defaultdict(lambda: FiveSecondBarAggregator(max_bars=240))
        self._lock = asyncio.Lock()

    async def add_book_ticker(self, ticker: BookTicker) -> None:
        symbol = ticker.symbol.upper()
        async with self._lock:
            self._book_tickers[symbol].append(ticker)

    async def add_depth_snapshot(self, depth: DepthSnapshot) -> None:
        symbol = depth.symbol.upper()
        async with self._lock:
            self._depth_snapshots[symbol].append(depth)

    async def add_trade(self, tick: MarketTick) -> None:
        if tick.quantity <= 0:
            return
        symbol = tick.symbol.upper()
        async with self._lock:
            self._trades[symbol].append(tick)
            is_bm = bool(tick.is_buyer_maker) if tick.is_buyer_maker is not None else False
            self._bar_aggregators[symbol].add_trade(
                price=tick.price,
                quantity=tick.quantity,
                is_buyer_maker=is_bm,
                event_time_ts=tick.event_time.timestamp(),
            )

    async def add_synthetic_tick(
        self,
        price: float,
        timestamp_ms: int | float,
        symbol: str = 'BTCUSDT',
        change: float | None = None,
    ) -> None:
        """Incorporate an incoming synthetic tick into the cache and 5s bar aggregator."""
        ts = (float(timestamp_ms) / 1000.0) if timestamp_ms > 1e11 else float(timestamp_ms)
        event_time = datetime.fromtimestamp(ts, tz=timezone.utc)
        sym = symbol.upper()
        tick = MarketTick(
            symbol=sym,
            price=price,
            quantity=1.0,
            event_time=event_time,
            provider='DETRADE_SYNTHETIC',
            is_buyer_maker=False,
        )
        book = BookTicker(
            symbol=sym,
            best_bid_price=price,
            best_bid_qty=10.0,
            best_ask_price=price,
            best_ask_qty=10.0,
            event_time=event_time,
            provider='DETRADE_SYNTHETIC',
        )
        async with self._lock:
            self._trades[sym].append(tick)
            self._book_tickers[sym].append(book)
            self._bar_aggregators[sym].add_synthetic_tick(price=price, timestamp_ms=timestamp_ms)

    async def clear(self, symbol: str) -> None:
        sym = symbol.upper()
        async with self._lock:
            self._book_tickers[sym].clear()
            self._depth_snapshots[sym].clear()
            self._trades[sym].clear()
            self._bar_aggregators[sym].clear()

    async def get_snapshot(
        self,
        symbol: str,
        max_book_age_seconds: float = 1.0,
        max_depth_age_seconds: float = 2.0,
        trade_lookback_seconds: float = 10.0,
        reference_time: datetime | None = None,
    ) -> MicrostructureSnapshot:
        sym = symbol.upper()
        now = reference_time or datetime.now(timezone.utc)
        async with self._lock:
            books = [b for b in self._book_tickers.get(sym, ()) if b.event_time <= now]
            depths = [d for d in self._depth_snapshots.get(sym, ()) if d.event_time <= now]
            trades = [t for t in self._trades.get(sym, ()) if t.event_time <= now]
            agg = self._bar_aggregators[sym]
            bars_5s = tuple(agg.get_closed_bars(limit=60))
            last_5s = agg.get_last_closed_bar()
            metrics_5s = agg.get_metrics()

        latest_book = books[-1] if books else None
        if settings.detrade_use_synthetic_feed and books:
            synthetic_books = [b for b in books if b.provider == 'DETRADE_SYNTHETIC']
            if synthetic_books:
                latest_book = synthetic_books[-1]
        latest_depth = depths[-1] if depths else None

        book_age = (now - latest_book.event_time).total_seconds() if latest_book else None
        depth_age = (now - latest_depth.event_time).total_seconds() if latest_depth else None

        fresh = (
            latest_book is not None
            and book_age is not None
            and 0.0 <= book_age <= max_book_age_seconds
            and (latest_depth is None or (depth_age is not None and 0.0 <= depth_age <= max_depth_age_seconds))
        )

        cutoff = now - timedelta(seconds=trade_lookback_seconds)
        recent_trades = tuple(t for t in trades if t.event_time >= cutoff)

        return MicrostructureSnapshot(
            symbol=sym,
            book_ticker=latest_book,
            depth=latest_depth,
            recent_ticks=recent_trades,
            book_ticker_age_seconds=book_age,
            depth_age_seconds=depth_age,
            is_fresh=fresh,
            last_5s_bar=last_5s,
            bars_5s=bars_5s,
            bar_metrics_5s=metrics_5s,
        )

    async def get_5s_bars(self, symbol: str, limit: int = 60) -> list[FiveSecondBar]:
        sym = symbol.upper()
        async with self._lock:
            return self._bar_aggregators[sym].get_closed_bars(limit=limit)

    async def get_last_5s_bar(self, symbol: str) -> FiveSecondBar | None:
        sym = symbol.upper()
        async with self._lock:
            return self._bar_aggregators[sym].get_last_closed_bar()

    async def get_5s_metrics(self, symbol: str) -> dict[str, Any]:
        sym = symbol.upper()
        async with self._lock:
            return self._bar_aggregators[sym].get_metrics()

    async def get_book_history(
        self, symbol: str, lookback_seconds: float = 10.0, reference_time: datetime | None = None
    ) -> list[BookTicker]:
        sym = symbol.upper()
        now = reference_time or datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=lookback_seconds)
        async with self._lock:
            books = list(self._book_tickers.get(sym, ()))
        return [b for b in books if cutoff <= b.event_time <= now]

    async def get_depth_history(
        self, symbol: str, lookback_seconds: float = 10.0, reference_time: datetime | None = None
    ) -> list[DepthSnapshot]:
        sym = symbol.upper()
        now = reference_time or datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=lookback_seconds)
        async with self._lock:
            depths = list(self._depth_snapshots.get(sym, ()))
        return [d for d in depths if cutoff <= d.event_time <= now]


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
