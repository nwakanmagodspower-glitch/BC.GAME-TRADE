from datetime import datetime, timezone
import pytest

from app.integrations.market_data.base import BookTicker, Candle, MarketTick
from app.models.entities import SignalDirection
from app.services.market_data import MicrostructureDataCache
from app.services.microstructure_intelligence import MicrostructureIntelligenceService


def create_candle(close_price: float) -> Candle:
    now = datetime.now(timezone.utc)
    return Candle(
        symbol="BTCUSDT",
        interval="1m",
        open_time=now,
        close_time=now,
        open=close_price,
        high=close_price + 5.0,
        low=close_price - 5.0,
        close=close_price,
        volume=10.0,
        quote_volume=10.0 * close_price,
        trade_count=100,
        taker_buy_base_volume=5.0,
        taker_buy_quote_volume=5.0 * close_price,
        closed=True,
        provider="BINANCE_SPOT",
    )


@pytest.mark.asyncio
async def test_microstructure_service_unwarmed_cache():
    cache = MicrostructureDataCache()
    service = MicrostructureIntelligenceService(cache=cache)
    result = await service.scan("BTCUSDT")

    assert result.direction == SignalDirection.NO_TRADE
    assert result.service_available is False
    assert "not warmed up" in result.reason.lower()


@pytest.mark.asyncio
async def test_microstructure_service_fresh_scan(monkeypatch):
    cache = MicrostructureDataCache()
    now = datetime.now(timezone.utc)

    book = BookTicker("BTCUSDT", 90000.0, 2.0, 90000.5, 1.0, now, "BINANCE_SPOT")
    await cache.add_book_ticker(book)
    await cache.add_trade(MarketTick("BTCUSDT", 90000.0, 1.0, now, "BINANCE_SPOT", is_buyer_maker=False))

    candles = [create_candle(90000.0) for _ in range(60)]

    async def mock_get_candles(*args, **kwargs):
        return candles

    from app.services.market_data import market_data_service
    monkeypatch.setattr(market_data_service, "get_cached_candles", mock_get_candles)

    service = MicrostructureIntelligenceService(cache=cache)
    result = await service.scan("BTCUSDT")

    assert result.service_available is True
    assert result.engine == "BTC_MICROSTRUCTURE_V2"
    assert result.reference_price == pytest.approx(90000.25)
    assert result.features is not None
