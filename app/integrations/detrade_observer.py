from __future__ import annotations

import asyncio
import base64
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
from app.integrations.detrade_token_provider import (
    DeTradeCredentials,
    DeTradeTokenProvider,
    detrade_token_provider,
)

settings = get_settings()
AUTH_FAILURE_CODES = {603, 3100}


@dataclass(frozen=True)
class DeTradeRoundObservation:
    round_id: str | None
    status: int | None
    current_time_ms: int | None
    trade_cutoff_time_ms: int | None
    price_start_time_ms: int | None
    price_end_time_ms: int | None
    start_price: float | None
    end_price: float | None
    previous_round_result: Any | None
    received_monotonic: float
    received_at: datetime

    @property
    def authoritative_cutoff_ms(self) -> int | None:
        return self.price_start_time_ms

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
        return self.data_age_ms < settings.detrade_stale_after_ms

    @property
    def phase(self) -> str:
        return {
            1001: 'BETTING',
            1002: 'START_PAY_OUT',
            1003: 'TRADE_CUTOFF',
            1004: 'PAY_OUT',
            1005: 'FINISHED',
            1006: 'READY_TO_START',
            1007: 'CANCELLED',
            1008: 'NON_TRADEABLE_TRANSITION',
        }.get(self.status, 'UNKNOWN')

    @property
    def can_trade(self) -> bool:
        remaining = self.remaining_ms
        return bool(
            self.fresh
            and self.status == 1001
            and self.round_id
            and remaining is not None
            and remaining > settings.detrade_latency_safety_margin_ms
        )


class DeTradeObserver:
    """Read-only authoritative BCGAME/DeTrade BTC/USD 5s round clock."""

    def __init__(self, token_provider: DeTradeTokenProvider = detrade_token_provider) -> None:
        self.token_provider = token_provider
        self.latest: DeTradeRoundObservation | None = None
        self.last_error: str | None = None
        self.connected: bool = False
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._probe_lock = asyncio.Lock()

    @staticmethod
    def _browser_cid() -> str:
        return base64.b64encode(settings.detrade_user_agent.encode('utf-8')).decode('ascii')

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

    def _connection_url(self, credentials: DeTradeCredentials) -> str:
        parts = urlsplit(settings.detrade_ws_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.update({
            'token': credentials.token,
            'device': settings.detrade_device,
            'type': str(credentials.account_type),
            'cid': self._browser_cid(),
        })
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    def _authenticated_message(self, credentials: DeTradeCredentials, cmd: str) -> dict[str, Any]:
        return {
            'cmd': cmd,
            'token': credentials.token,
            'cid': self._browser_cid(),
            'reqId': str(uuid.uuid4()),
        }

    @staticmethod
    def _encode_message(payload: dict[str, Any]) -> bytes:
        serialized = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
        return zlib.compress(serialized.encode('utf-8'))

    @staticmethod
    def _decode_frame(frame: str | bytes) -> Any:
        if isinstance(frame, str):
            return json.loads(frame)
        raw = bytes(frame)
        try:
            return json.loads(zlib.decompress(raw).decode('utf-8'))
        except (zlib.error, UnicodeDecodeError, json.JSONDecodeError):
            pass
        try:
            return json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        try:
            return json.loads(zlib.decompress(raw, -zlib.MAX_WBITS).decode('utf-8'))
        except (zlib.error, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError('Unsupported DeTrade WebSocket frame format') from exc

    @classmethod
    def _contains_auth_failure(cls, value: Any, depth: int = 0) -> bool:
        if depth > 8:
            return False
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in {'code', 'status'}:
                    try:
                        if int(child) in AUTH_FAILURE_CODES:
                            return True
                    except (TypeError, ValueError):
                        pass
                if cls._contains_auth_failure(child, depth + 1):
                    return True
        elif isinstance(value, list):
            return any(cls._contains_auth_failure(child, depth + 1) for child in value)
        return False

    @classmethod
    def _find_round_payload(cls, value: Any, depth: int = 0) -> dict[str, Any] | None:
        if depth > 8:
            return None
        if isinstance(value, dict):
            keys = set(value)
            if {'id', 'status', 'currentTime', 'priceStartTime', 'priceEndTime'} <= keys:
                return value
            for key, nested in value.items():
                if any(secret in str(key).lower() for secret in ('token', 'cookie', 'authorization', 'session', 'jwt', 'accesscode')):
                    continue
                found = cls._find_round_payload(nested, depth + 1)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for nested in value:
                found = cls._find_round_payload(nested, depth + 1)
                if found is not None:
                    return found
        return None

    @staticmethod
    def _as_int(value: Any) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            return None
        if 1_000_000_000 <= number < 10_000_000_000:
            number *= 1000
        return number

    @staticmethod
    def _as_float(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    async def _consume(self, decoded: Any) -> bool:
        if self._contains_auth_failure(decoded):
            await self.token_provider.invalidate()
            self.last_error = 'DeTrade authorization expired or requires refresh.'
            return False
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
            start_price=self._as_float(payload.get('startPrice')),
            end_price=self._as_float(payload.get('endPrice')),
            previous_round_result=payload.get('previousRoundResult'),
            received_monotonic=time.monotonic(),
            received_at=datetime.now(timezone.utc),
        )
        self.last_error = None
        return True

    async def _heartbeat(self, ws: Any, credentials: DeTradeCredentials) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(settings.detrade_ping_interval_seconds)
            await ws.send(self._encode_message(self._authenticated_message(credentials, 'ping')))

    async def _session(self, credentials: DeTradeCredentials, *, first_frame_only: bool) -> DeTradeRoundObservation | None:
        try:
            async with websockets.connect(
                self._connection_url(credentials),
                origin=settings.detrade_origin,
                additional_headers={'User-Agent': settings.detrade_user_agent},
                ping_interval=None,
                close_timeout=2,
                max_size=settings.detrade_max_frame_bytes,
                compression=None,
            ) as ws:
                self.connected = True
                await ws.send(self._encode_message(
                    self._authenticated_message(credentials, settings.detrade_subscription_cmd)
                ))
                heartbeat = asyncio.create_task(self._heartbeat(ws, credentials))
                try:
                    async for frame in ws:
                        try:
                            decoded = self._decode_frame(frame)
                        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                            self.last_error = 'A DeTrade frame could not be decoded.'
                            continue
                        if self._contains_auth_failure(decoded):
                            await self.token_provider.invalidate()
                            self.last_error = 'DeTrade authorization expired or requires refresh.'
                            return None
                        if await self._consume(decoded) and first_frame_only:
                            return self.latest
                finally:
                    heartbeat.cancel()
                    try:
                        await heartbeat
                    except asyncio.CancelledError:
                        pass
        except asyncio.CancelledError:
            raise
        except Exception:
            self.last_error = 'DeTrade connection failed.'
        finally:
            self.connected = False
        return self.latest if self.latest and self.latest.fresh else None

    async def probe(self, timeout_seconds: float | None = None) -> DeTradeRoundObservation | None:
        if not settings.detrade_ws_enabled:
            self.last_error = 'DeTrade observer is disabled.'
            return None
        if self.latest and self.latest.fresh:
            return self.latest

        credentials = await self.token_provider.get_credentials()
        if credentials is None:
            self.last_error = 'DeTrade authorization is not available yet.'
            return None

        timeout = timeout_seconds or settings.detrade_probe_timeout_seconds
        if self._task and not self._task.done():
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self.latest and self.latest.fresh:
                    return self.latest
                if self.last_error and 'authorization' in self.last_error.lower():
                    return None
                await asyncio.sleep(0.05)
            self.last_error = 'DeTrade timer probe timed out.'
            return None

        async with self._probe_lock:
            try:
                return await asyncio.wait_for(self._session(credentials, first_frame_only=True), timeout=timeout)
            except TimeoutError:
                self.connected = False
                self.last_error = 'DeTrade timer probe timed out.'
                return None

    async def _run(self) -> None:
        backoff = max(1.0, settings.detrade_reconnect_seconds)
        while not self._stop.is_set():
            credentials = await self.token_provider.get_credentials(force_refresh=False)
            if credentials is None:
                self.last_error = 'DeTrade authorization is not available yet.'
                await asyncio.sleep(min(backoff, 5.0))
                backoff = min(backoff * 1.7, settings.detrade_reconnect_max_seconds)
                continue
            await self._session(credentials, first_frame_only=False)
            if self._stop.is_set():
                return
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.7, settings.detrade_reconnect_max_seconds)
            if self.latest and self.latest.fresh:
                backoff = max(1.0, settings.detrade_reconnect_seconds)


detrade_observer = DeTradeObserver()
