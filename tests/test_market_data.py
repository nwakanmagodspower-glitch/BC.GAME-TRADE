import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.integrations.market_data.base import Candle, MarketTick
from app.services.market_data import MarketDataCache


def test_market_data_cache_marks_fresh_and_stale_ticks():
    async def run():
        cache = MarketDataCache()
        now = datetime.now(timezone.utc)

        await cache.set_tick(
            MarketTick(
                symbol='BTCUSDT',
                price=60000.0,
                quantity=0.25,
                event_time=now,
                provider='TEST',
                is_buyer_maker=False,
            )
        )
        fresh = await cache.get_snapshot('BTCUSDT', max_age_seconds=3)
        assert fresh is not None
        assert fresh.fresh is True
        assert fresh.price == 60000.0

        await cache.set_tick(
            MarketTick(
                symbol='BTCUSDT',
                price=59900.0,
                quantity=0.1,
                event_time=now - timedelta(seconds=10),
                provider='TEST',
                is_buyer_maker=True,
            )
        )
        stale = await cache.get_snapshot('BTCUSDT', max_age_seconds=3)
        assert stale is not None
        assert stale.fresh is False
        assert stale.age_seconds >= 9

    asyncio.run(run())


def test_market_data_cache_keeps_only_recent_trade_window():
    async def run():
        cache = MarketDataCache(trade_buffer_size=10)
        now = datetime.now(timezone.utc)
        await cache.set_tick(MarketTick('BTCUSDT', 60000, 1.0, now - timedelta(seconds=20), 'TEST', True))
        await cache.set_tick(MarketTick('BTCUSDT', 60010, 2.0, now - timedelta(seconds=4), 'TEST', False))
        await cache.set_tick(MarketTick('BTCUSDT', 60020, 3.0, now - timedelta(seconds=1), 'TEST', False))

        ticks = await cache.get_recent_ticks('BTCUSDT', lookback_seconds=5)
        assert len(ticks) == 2
        assert [tick.price for tick in ticks] == [60010, 60020]

    asyncio.run(run())


def test_market_data_cache_rejects_future_ticks_and_uses_provider_candle_time():
    async def run():
        cache = MarketDataCache(max_future_skew_seconds=1)
        now = datetime.now(timezone.utc)
        with pytest.raises(ValueError, match='future'):
            await cache.set_tick(MarketTick('BTCUSDT', 60000, 1.0, now + timedelta(seconds=5), 'TEST', False))

        stale_candle = Candle(
            symbol='BTCUSDT', interval='1m', open_time=now - timedelta(minutes=2),
            close_time=now - timedelta(minutes=1), open=1, high=2, low=1, close=2,
            volume=1, quote_volume=1, trade_count=1, taker_buy_base_volume=1,
            taker_buy_quote_volume=1, closed=True, provider='TEST',
        )
        await cache.set_candles('BTCUSDT', [stale_candle])
        assert await cache.get_candles('BTCUSDT', max_age_seconds=60) is None
        age = await cache.get_candle_age_seconds('BTCUSDT')
        assert age is not None and age >= 119

        fresh_candle = Candle(
            symbol='BTCUSDT', interval='1m', open_time=now - timedelta(seconds=5),
            close_time=now + timedelta(seconds=55), open=1, high=2, low=1, close=2,
            volume=1, quote_volume=1, trade_count=1, taker_buy_base_volume=1,
            taker_buy_quote_volume=1, closed=False, provider='TEST',
        )
        await cache.set_candles('BTCUSDT', [fresh_candle])
        assert await cache.get_candles('BTCUSDT', max_age_seconds=60) is not None

    asyncio.run(run())
