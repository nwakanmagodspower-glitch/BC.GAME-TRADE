import asyncio

from app.services.webhook_backpressure import WebhookBackpressure, telegram_update_user_id


def test_extracts_telegram_user_id():
    assert telegram_update_user_id({'callback_query': {'from': {'id': 123}}}) == 123
    assert telegram_update_user_id({'message': {'from': {'id': 456}}}) == 456
    assert telegram_update_user_id({'channel_post': {'chat': {'id': -1}}}) is None


def test_per_user_limit_and_global_concurrency():
    async def run():
        limiter = WebhookBackpressure(
            max_concurrency=1,
            queue_timeout_seconds=0.01,
            user_limit=2,
            user_window_seconds=10,
        )
        assert await limiter.allow_user(1) is True
        assert await limiter.allow_user(1) is True
        assert await limiter.allow_user(1) is False

        assert await limiter.acquire() is True
        assert await limiter.acquire() is False
        limiter.release()
        assert await limiter.acquire() is True
        limiter.release()

    asyncio.run(run())
