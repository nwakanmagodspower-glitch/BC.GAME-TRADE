from __future__ import annotations

import asyncio
import time
from collections import deque

from app.core.config import get_settings

settings = get_settings()


class WebhookBackpressure:
    """Bound concurrent webhook work and abusive per-user update bursts.

    This is intentionally process-local. It protects each web instance from a
    burst of valid Telegram updates before they reach database-heavy handlers.
    Per-user signal cooldown/database invariants remain the durable trading gate.
    """

    def __init__(
        self,
        max_concurrency: int,
        queue_timeout_seconds: float,
        user_limit: int,
        user_window_seconds: float,
    ):
        if max_concurrency < 1 or user_limit < 1:
            raise ValueError('webhook limits must be positive')
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self.queue_timeout_seconds = max(0.0, queue_timeout_seconds)
        self.user_limit = user_limit
        self.user_window_seconds = max(0.1, user_window_seconds)
        self._user_events: dict[int, deque[float]] = {}
        self._user_lock = asyncio.Lock()

    async def allow_user(self, user_id: int | None) -> bool:
        if user_id is None:
            return True
        now = time.monotonic()
        cutoff = now - self.user_window_seconds
        async with self._user_lock:
            events = self._user_events.setdefault(user_id, deque())
            while events and events[0] < cutoff:
                events.popleft()
            if len(events) >= self.user_limit:
                return False
            events.append(now)

            # Opportunistic bounded-memory cleanup for inactive users.
            if len(self._user_events) > 2048:
                stale = [uid for uid, q in self._user_events.items() if not q or q[-1] < cutoff]
                for uid in stale:
                    self._user_events.pop(uid, None)
            return True

    async def acquire(self) -> bool:
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=self.queue_timeout_seconds)
            return True
        except TimeoutError:
            return False

    def release(self) -> None:
        self._semaphore.release()


def telegram_update_user_id(payload: dict) -> int | None:
    """Extract the initiating Telegram user ID from common update shapes."""
    for key in ('message', 'edited_message', 'channel_post', 'edited_channel_post'):
        item = payload.get(key)
        if isinstance(item, dict):
            sender = item.get('from')
            if isinstance(sender, dict) and isinstance(sender.get('id'), int):
                return sender['id']
    for key in ('callback_query', 'inline_query', 'chosen_inline_result', 'shipping_query', 'pre_checkout_query', 'chat_member', 'my_chat_member'):
        item = payload.get(key)
        if isinstance(item, dict):
            sender = item.get('from')
            if isinstance(sender, dict) and isinstance(sender.get('id'), int):
                return sender['id']
    return None


webhook_backpressure = WebhookBackpressure(
    max_concurrency=settings.telegram_webhook_max_concurrency,
    queue_timeout_seconds=settings.telegram_webhook_queue_timeout_seconds,
    user_limit=settings.telegram_user_update_limit,
    user_window_seconds=settings.telegram_user_update_window_seconds,
)
