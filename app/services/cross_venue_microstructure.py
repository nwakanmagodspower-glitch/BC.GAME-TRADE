from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import websockets

from app.core.config import get_settings

settings = get_settings()


@dataclass(frozen=True)
class VenueBookSnapshot:
    venue: str
    best_bid: float
    best_ask: float
    bid_qty: float
    ask_qty: float
    depth_bid_qty: float
    depth_ask_qty: float
    event_time: datetime

    @property
    def midpoint(self) -> float:
        return (self.best_bid + self.best_ask) / 2.0

    @property
    def spread_bps(self) -> float:
        mid = self.midpoint
        return ((self.best_ask - self.best_bid) / mid * 10_000.0) if mid > 0 else 0.0

    @property
    def imbalance(self) -> float:
        total = self.depth_bid_qty + self.depth_ask_qty
        return (self.depth_bid_qty - self.depth_ask_qty) / total if total > 0 else 0.0

    @property
    def microprice(self) -> float:
        total = self.bid_qty + self.ask_qty
        if total <= 0:
            return self.midpoint
        # More bid size shifts fair value toward the ask; more ask size shifts it toward the bid.
        return ((self.best_ask * self.bid_qty) + (self.best_bid * self.ask_qty)) / total

    @property
    def microprice_bias_bps(self) -> float:
        mid = self.midpoint
        return ((self.microprice - mid) / mid * 10_000.0) if mid > 0 else 0.0

    @property
    def age_seconds(self) -> float:
        return max(0.0, (datetime.now(timezone.utc) - self.event_time).total_seconds())


@dataclass(frozen=True)
class CrossVenueSnapshot:
    binance: VenueBookSnapshot | None
    bybit: VenueBookSnapshot | None

    @property
    def fresh(self) -> bool:
        max_age = settings.cross_venue_max_age_seconds
        return bool(
            self.binance is not None
            and self.bybit is not None
            and self.binance.age_seconds <= max_age
            and self.bybit.age_seconds <= max_age
        )

    @property
    def consensus(self) -> str:
        if not self.fresh:
            return 'UNAVAILABLE'
        b = self.binance
        y = self.bybit
        assert b is not None and y is not None
        bull = (
            b.imbalance >= settings.cross_venue_imbalance_threshold
            and y.imbalance >= settings.cross_venue_imbalance_threshold
            and b.microprice_bias_bps >= settings.cross_venue_microprice_bias_bps
            and y.microprice_bias_bps >= settings.cross_venue_microprice_bias_bps
        )
        bear = (
            b.imbalance <= -settings.cross_venue_imbalance_threshold
            and y.imbalance <= -settings.cross_venue_imbalance_threshold
            and b.microprice_bias_bps <= -settings.cross_venue_microprice_bias_bps
            and y.microprice_bias_bps <= -settings.cross_venue_microprice_bias_bps
        )
        if bull:
            return 'UP'
        if bear:
            return 'DOWN'
        return 'MIXED'

    @property
    def healthy_spread(self) -> bool:
        if not self.fresh:
            return False
        assert self.binance is not None and self.bybit is not None
        limit = settings.cross_venue_max_spread_bps
        return self.binance.spread_bps <= limit and self.bybit.spread_bps <= limit

    def to_dict(self) -> dict[str, Any]:
        def venue(v: VenueBookSnapshot | None) -> dict[str, Any] | None:
            if v is None:
                return None
            return {
                'imbalance': round(v.imbalance, 5),
                'microprice_bias_bps': round(v.microprice_bias_bps, 5),
                'spread_bps': round(v.spread_bps, 5),
                'age_seconds': round(v.age_seconds, 3),
            }
        return {
            'fresh': self.fresh,
            'consensus': self.consensus,
            'healthy_spread': self.healthy_spread,
            'binance': venue(self.binance),
            'bybit': venue(self.bybit),
        }


class CrossVenueMicrostructureService:
    def __init__(self) -> None:
        self._books: dict[str, VenueBookSnapshot] = {}
        self._tasks: list[asyncio.Task] = []
        self._stop = asyncio.Event()
        self.last_error: dict[str, str | None] = {'BINANCE': None, 'BYBIT': None}

    async def start(self) -> None:
        if not settings.cross_venue_enabled or any(not task.done() for task in self._tasks):
            return
        self._stop.clear()
        self._tasks = [
            asyncio.create_task(self._run_binance(), name='microstructure-binance'),
            asyncio.create_task(self._run_bybit(), name='microstructure-bybit'),
        ]

    async def stop(self) -> None:
        self._stop.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks = []

    def snapshot(self) -> CrossVenueSnapshot:
        return CrossVenueSnapshot(
            binance=self._books.get('BINANCE'),
            bybit=self._books.get('BYBIT'),
        )

    @staticmethod
    def _build_snapshot(venue: str, bids: list, asks: list, event_time: datetime | None = None) -> VenueBookSnapshot | None:
        try:
            normalized_bids = [(float(p), float(q)) for p, q, *_ in bids if float(q) > 0]
            normalized_asks = [(float(p), float(q)) for p, q, *_ in asks if float(q) > 0]
        except (TypeError, ValueError):
            return None
        if not normalized_bids or not normalized_asks:
            return None
        normalized_bids.sort(key=lambda item: item[0], reverse=True)
        normalized_asks.sort(key=lambda item: item[0])
        top_bids = normalized_bids[: settings.cross_venue_depth_levels]
        top_asks = normalized_asks[: settings.cross_venue_depth_levels]
        return VenueBookSnapshot(
            venue=venue,
            best_bid=top_bids[0][0],
            best_ask=top_asks[0][0],
            bid_qty=top_bids[0][1],
            ask_qty=top_asks[0][1],
            depth_bid_qty=sum(q for _, q in top_bids),
            depth_ask_qty=sum(q for _, q in top_asks),
            event_time=event_time or datetime.now(timezone.utc),
        )

    async def _run_binance(self) -> None:
        url = settings.cross_venue_binance_ws_url
        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=10, max_size=1_000_000) as ws:
                    self.last_error['BINANCE'] = None
                    backoff = 1.0
                    async for frame in ws:
                        if self._stop.is_set():
                            return
                        data = json.loads(frame)
                        bids = data.get('b') or data.get('bids') or []
                        asks = data.get('a') or data.get('asks') or []
                        snap = self._build_snapshot('BINANCE', bids, asks)
                        if snap is not None:
                            self._books['BINANCE'] = snap
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error['BINANCE'] = type(exc).__name__
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.7, 15.0)

    async def _run_bybit(self) -> None:
        url = settings.cross_venue_bybit_ws_url
        topic = f'orderbook.{settings.cross_venue_depth_levels}.BTCUSDT'
        bids: dict[float, float] = {}
        asks: dict[float, float] = {}
        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=10, max_size=1_000_000) as ws:
                    await ws.send(json.dumps({'op': 'subscribe', 'args': [topic]}))
                    self.last_error['BYBIT'] = None
                    backoff = 1.0
                    async for frame in ws:
                        if self._stop.is_set():
                            return
                        payload = json.loads(frame)
                        if payload.get('topic') != topic:
                            continue
                        data = payload.get('data') or {}
                        msg_type = payload.get('type')
                        if msg_type == 'snapshot':
                            bids.clear(); asks.clear()
                        for raw_price, raw_qty, *_ in data.get('b', []):
                            price = float(raw_price); qty = float(raw_qty)
                            if qty <= 0: bids.pop(price, None)
                            else: bids[price] = qty
                        for raw_price, raw_qty, *_ in data.get('a', []):
                            price = float(raw_price); qty = float(raw_qty)
                            if qty <= 0: asks.pop(price, None)
                            else: asks[price] = qty
                        snap = self._build_snapshot(
                            'BYBIT',
                            sorted(bids.items(), reverse=True)[: settings.cross_venue_depth_levels],
                            sorted(asks.items())[: settings.cross_venue_depth_levels],
                        )
                        if snap is not None:
                            self._books['BYBIT'] = snap
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error['BYBIT'] = type(exc).__name__
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.7, 15.0)


cross_venue_microstructure_service = CrossVenueMicrostructureService()
