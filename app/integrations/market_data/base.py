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


def ms_to_datetime(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
