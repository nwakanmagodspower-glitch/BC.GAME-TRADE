from __future__ import annotations

import asyncio
import json
import time
import uuid
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import websockets

from app.core.config import get_settings

settings = get_settings()


@dataclass(frozen=True)
class DeTradeRoundObservation:
    round_id: str | None
    status: int | None
    current_time_ms: int | None
    trade_cutoff_time_ms: int | None
    price_start_time_ms: int | None
    price_end_time_ms: int | None
    previous_round_result: Any | None
    received_monotonic: float
    received_at: datetime

    @property
    def authoritative_cutoff_ms(self) -> int | None:
        return self.trade_cutoff_time_ms or self.price_start_time_ms

    @property
    def data_age_ms(self) -> int:
        return max(0, int((time.monotonic() - self.received_monotonic) * 1000))

    @property
    def estimated_server_time_ms(self) -> int | None:
        if self.current_time_ms is None:
            return None
        return self.current_time_ms + self.data_age_ms

    @property
    def remaining_ms(self) -> int | None:
        cutoff = self.authoritative_cutoff_ms
        server_now = self.estimated_server_time_ms
        if cutoff is None or server_now is None:
            return None
        return max(0, int(cutoff - server_now))

    @property
    def fresh(self) -> bool:
        return self.data_age_ms <= settings.detrade_stale_after_ms

    @property
    def phase(self) -> str:
        return {
            1001: 'BETTING',
            1003: 'TRADE_CUTOFF',
            1002: 'PAYOUT_PROCESSING',
            1004: 'PAYOUT_PROCESSING',
            1005: 'FINISHED',
            1006: 'PREPARING_NEXT_ROUND',
            1007: 'CANCELLED',
        }.get(self.status, 'UNKNOWN')

    @property
    def can_trade(self) -> bool:
        remaining = self.remaining_ms
        return bool(
            self.fresh
            and self.status == 1001
            and remaining is not None
            and remaining > settings.detrade_latency_safety_margin_ms
        )


class DeTradeObserver:
    """Observation-only DeTrade round feed.

    Reverse-engineered field names and routes are configurable. No token is ever
    printed or included in diagnostics. This component does not place orders and
    does not control the live signal engine while observation mode is being tested.
    """

    def __init__(self) -> None:
        self.latest: DeTradeRoundObservation | None = None
        self.last_error: str | None = None
        self.connected: bool = False
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if not settings.detrade_ws_enabled:
            return
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name='detrade-round-observer')

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self.connected = False

    def _connection_url(self) -> str:
        base = settings.detrade_ws_url
        if settings.detrade_auth_mode.upper() != 'QUERY' or not settings.detrade_ws_token:
            return base
        parts = urlsplit(base)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.update({
            'token': settings.detrade_ws_token,
            'device': settings.detrade_device,
            'type': str(settings.detrade_client_type),
        })
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    def _subscription_message(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            'cmd': settings.detrade_subscription_cmd,
            'cid': uuid.uuid4().hex,
            'reqId': uuid.uuid4().hex,
        }
        if settings.detrade_auth_mode.upper() == 'MESSAGE' and settings.detrade_ws_token:
            payload['token'] = settings.detrade_ws_token
        return payload

    @staticmethod
    def _decode_frame(frame: str | bytes) -> Any:
        if isinstance(frame, str):
            return json.loads(frame)

        candidates: list[bytes] = [frame]
        try:
            candidates.insert(0, zlib.decompress(frame))
        except zlib.error:
            try:
                candidates.insert(0, zlib.decompress(frame, -zlib.MAX_WBITS))
            except zlib.error:
                pass

        last_error: Exception | None = None
        for candidate in candidates:
            try:
                return json.loads(candidate.decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                last_error = exc
        raise ValueError('Unsupported DeTrade WebSocket frame format') from last_error

    @classmethod
    def _find_round_payload(cls, value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            keys = set(value)
            if {'status', 'currentTime'} <= keys and ('priceStartTime' in keys or 'tradeCutoffTime' in keys):
                return value
            for nested in value.values():
                found = cls._find_round_payload(nested)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for nested in value:
                found = cls._find_round_payload(nested)
                if found is not None:
                    return found
        return None

    @staticmethod
    def _as_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            return None
        if 1_000_000_000 <= number < 10_000_000_000:
            number *= 1000
        return number

    def _consume(self, decoded: Any) -> bool:
        payload = self._find_round_payload(decoded)
        if payload is None:
            return False
        self.latest = DeTradeRoundObservation(
            round_id=str(payload.get('id')) if payload.get('id') is not None else None,
            status=self._as_int(payload.get('status')),
            current_time_ms=self._as_int(payload.get('currentTime')),
            trade_cutoff_time_ms=self._as_int(payload.get('tradeCutoffTime')),
            price_start_time_ms=self._as_int(payload.get('priceStartTime')),
            price_end_time_ms=self._as_int(payload.get('priceEndTime')),
            previous_round_result=payload.get('previousRoundResult'),
            received_monotonic=time.monotonic(),
            received_at=datetime.now(timezone.utc),
        )
        self.last_error = None
        return True

    async def probe(self, timeout_seconds: float = 6.0) -> DeTradeRoundObservation | None:
        """Connect briefly, capture one valid round payload, then disconnect."""
        if not settings.detrade_ws_enabled:
            self.last_error = 'DeTrade observer is disabled.'
            return None
        if not settings.detrade_ws_token:
            self.last_error = 'DeTrade observer token is not configured.'
            return None

        async def _probe() -> DeTradeRoundObservation | None:
            try:
                async with websockets.connect(
                    self._connection_url(),
                    origin=settings.detrade_origin,
                    additional_headers={'User-Agent': settings.detrade_user_agent},
                    ping_interval=None,
                    close_timeout=3,
                    max_size=settings.detrade_max_frame_bytes,
                    compression=None,
                ) as ws:
                    self.connected = True
                    await ws.send(json.dumps(self._subscription_message(), separators=(',', ':')))
                    async for frame in ws:
                        try:
                            if self._consume(self._decode_frame(frame)):
                                return self.latest
                        except Exception as exc:
                            self.last_error = f'Frame decode error: {type(exc).__name__}'
                    return None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = f'Connection error: {type(exc).__name__}'
                return None
            finally:
                self.connected = False

        try:
            return await asyncio.wait_for(_probe(), timeout=timeout_seconds)
        except TimeoutError:
            self.connected = False
            self.last_error = 'Probe timed out before a valid round frame was received.'
            return None

    async def _observe_once(self) -> None:
        if not settings.detrade_ws_token:
            self.last_error = 'DeTrade observer token is not configured.'
            await asyncio.sleep(settings.detrade_reconnect_seconds)
            return
        try:
            async with websockets.connect(
                self._connection_url(),
                origin=settings.detrade_origin,
                additional_headers={'User-Agent': settings.detrade_user_agent},
                ping_interval=settings.detrade_ping_interval_seconds,
                ping_timeout=settings.detrade_ping_timeout_seconds,
                close_timeout=5,
                max_size=settings.detrade_max_frame_bytes,
                compression=None,
            ) as ws:
                self.connected = True
                await ws.send(json.dumps(self._subscription_message(), separators=(',', ':')))
                async for frame in ws:
                    if self._stop.is_set():
                        break
                    try:
                        self._consume(self._decode_frame(frame))
                    except Exception as exc:
                        self.last_error = f'Frame decode error: {type(exc).__name__}'
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_error = f'Connection error: {type(exc).__name__}'
        finally:
            self.connected = False

    async def _run(self) -> None:
        backoff = max(1.0, settings.detrade_reconnect_seconds)
        while not self._stop.is_set():
            await self._observe_once()
            if self._stop.is_set():
                return
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.7, settings.detrade_reconnect_max_seconds)
            if self.latest and self.latest.fresh:
                backoff = max(1.0, settings.detrade_reconnect_seconds)


detrade_observer = DeTradeObserver()
