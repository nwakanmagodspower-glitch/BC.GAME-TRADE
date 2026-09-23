from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class MarketTick:
    symbol: str
    price: float
    quantity: float
    event_time: datetime
    provider: str
    is_buyer_maker: bool | None = None


@dataclass(frozen=True)
class Candle:
    symbol: str
    interval: str
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    trade_count: int
    taker_buy_base_volume: float
    taker_buy_quote_volume: float
    closed: bool
    provider: str


@dataclass(frozen=True)
class BookTicker:
    symbol: str
    best_bid_price: float
    best_bid_qty: float
    best_ask_price: float
    best_ask_qty: float
    event_time: datetime
    provider: str

    @property
    def mid_price(self) -> float:
        return (self.best_bid_price + self.best_ask_price) / 2.0

    @property
    def spread(self) -> float:
        return self.best_ask_price - self.best_bid_price

    @property
    def spread_bps(self) -> float:
        mid = self.mid_price
        return (self.spread / mid * 10000.0) if mid > 0 else 0.0


@dataclass(frozen=True)
class DepthLevel:
    price: float
    quantity: float


@dataclass(frozen=True)
class DepthSnapshot:
    symbol: str
    bids: tuple[DepthLevel, ...]
    asks: tuple[DepthLevel, ...]
    event_time: datetime
    provider: str


class MarketDataProvider(ABC):
    name: str

    @abstractmethod
    async def fetch_latest_price(self, symbol: str) -> MarketTick:
        raise NotImplementedError

    @abstractmethod
    async def fetch_candles(self, symbol: str, interval: str, limit: int) -> list[Candle]:
        raise NotImplementedError

    @abstractmethod
    async def stream_ticks(self, symbol: str):
        """Yield normalized MarketTick objects indefinitely until cancelled."""
        raise NotImplementedError

    async def stream_book_ticker(self, symbol: str):
        """Yield normalized BookTicker objects indefinitely until cancelled."""
        raise NotImplementedError

    async def stream_depth(self, symbol: str, levels: int = 5, update_speed_ms: int = 100):
        """Yield normalized DepthSnapshot objects indefinitely until cancelled."""
        raise NotImplementedError


def ms_to_datetime(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
