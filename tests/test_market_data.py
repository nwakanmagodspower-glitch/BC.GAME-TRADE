import asyncio
from datetime import datetime, timedelta, timezone

from app.integrations.market_data.base import MarketTick
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
