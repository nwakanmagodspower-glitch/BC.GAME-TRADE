from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
import zlib
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
import websockets

from app.core.config import get_settings
from app.integrations.detrade_token_provider import (
    DeTradeCredentials,
    DeTradeTokenProvider,
    detrade_token_provider,
)
from app.integrations.market_data.base import BookTicker, MarketTick
from app.integrations.market_data.five_second_bar import FiveSecondBar, FiveSecondBarAggregator

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
    def authoritative_deadline_monotonic(self) -> float | None:
        cutoff = self.authoritative_cutoff_ms
        if cutoff is None or self.current_time_ms is None:
            return None
        return self.received_monotonic + max(0, cutoff - self.current_time_ms) / 1000

    @property
    def remaining_ms(self) -> int | None:
        deadline = self.authoritative_deadline_monotonic
        if deadline is None:
            return None
        return max(0, int((deadline - time.monotonic()) * 1000))

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

    def to_public_dict(self, include_pricing: bool = False) -> dict[str, Any]:
        """Normalized non-secret timer state suitable for health/admin output."""
        data = {
            'roundId': self.round_id,
            'status': self.status,
            'phase': self.phase,
            'remainingMilliseconds': self.remaining_ms,
            'dataAgeMilliseconds': self.data_age_ms,
            'canTrade': self.can_trade,
            'priceStartTime': self.price_start_time_ms,
            'priceEndTime': self.price_end_time_ms,
        }
        if include_pricing:
            data['startPrice'] = self.start_price
            data['endPrice'] = self.end_price
        return data


class DeTradeObserver:
    """Read-only authoritative BCGAME/DeTrade BTC/USD 5s round clock & synthetic tick listener."""

    def __init__(
        self,
        token_provider: DeTradeTokenProvider = detrade_token_provider,
        on_observation: Any = None,
        on_tick: Any = None,
        bar_aggregator: FiveSecondBarAggregator | None = None,
    ) -> None:
        self.token_provider = token_provider
        self.on_observation = on_observation
        self.on_tick = on_tick
        self.bar_aggregator = bar_aggregator or FiveSecondBarAggregator(max_bars=240)
        self._recent_ticks: deque[MarketTick] = deque(maxlen=240)
        self.latest: DeTradeRoundObservation | None = None
        self.latest_tick: dict[str, Any] | None = None
        self.last_error: str | None = None
        self.connected: bool = False
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._probe_lock = asyncio.Lock()
        self._observation_event = asyncio.Event()
        self._force_credential_refresh = False
        self._last_tick_price: float | None = None

    @staticmethod
    def _browser_cid() -> str:
        return base64.b64encode(settings.detrade_user_agent.encode('utf-8')).decode('ascii')

    async def bootstrap_history(self, seconds: int = 120) -> int:
        """Pre-warm the bar aggregator from DeTrade's public historical ticker REST API."""
        url = f"{settings.detrade_kline_history_url}?symbol={settings.detrade_synthetic_symbol}&seconds={seconds}"
        try:
            async with httpx.AsyncClient(timeout=6.0, headers={'User-Agent': settings.detrade_user_agent}) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return 0
                payload = resp.json()
                ticks = payload.get('data') or []
                if not isinstance(ticks, list):
                    return 0
                ticks_sorted = sorted(ticks, key=lambda x: int(x.get('t', 0)))
                count = 0
                for item in ticks_sorted:
                    try:
                        p = float(item['p'])
                        t = int(item['t'])
                        self.bar_aggregator.add_synthetic_tick(price=p, timestamp_ms=t)
                        self._last_tick_price = p
                        ts = (float(t) / 1000.0) if t > 1e11 else float(t)
                        ev_time = datetime.fromtimestamp(ts, tz=timezone.utc)
                        self._recent_ticks.append(
                            MarketTick(
                                symbol=settings.analysis_pair,
                                price=p,
                                quantity=1.0,
                                event_time=ev_time,
                                provider='DETRADE_SYNTHETIC',
                                is_buyer_maker=False,
                            )
                        )
                        count += 1
                        if self.on_tick is not None:
                            try:
                                res = self.on_tick({
                                    'price': p,
                                    'timestamp_ms': t,
                                    'symbol': str(item.get('s', settings.detrade_synthetic_symbol)),
                                    'change': float(item['c']) if 'c' in item and item['c'] is not None else None,
                                    'source': 'REST_BOOTSTRAP',
                                })
                                if asyncio.iscoroutine(res):
                                    await res
                            except Exception:
                                pass
                    except (KeyError, ValueError, TypeError):
                        continue
                if ticks_sorted and count > 0:
                    last_item = ticks_sorted[-1]
                    try:
                        self.latest_tick = {
                            'price': float(last_item['p']),
                            'timestamp_ms': int(last_item['t']),
                            'symbol': str(last_item.get('s', settings.detrade_synthetic_symbol)),
                            'change': float(last_item['c']) if 'c' in last_item and last_item['c'] is not None else None,
                            'received_monotonic': time.monotonic(),
                            'received_at': datetime.now(timezone.utc),
                            'source': 'REST_BOOTSTRAP',
                        }
                    except (KeyError, ValueError, TypeError):
                        pass
                return count
        except Exception:
            return 0

    def get_synthetic_snapshot(self, symbol: str = 'BTCUSDT', max_age_seconds: float = 3.0) -> Any:
        """Return a 100% pure DeTrade synthetic microstructure snapshot with zero external exchange contamination."""
        if self.latest_tick is None:
            return None
        now_mono = time.monotonic()
        age = now_mono - float(self.latest_tick.get('received_monotonic', 0))
        if age > max_age_seconds or age < 0:
            return None
        p = float(self.latest_tick['price'])
        now_dt = datetime.now(timezone.utc)
        from app.services.market_data import MicrostructureSnapshot
        book = BookTicker(
            symbol=symbol.upper(),
            best_bid_price=p,
            best_bid_qty=10.0,
            best_ask_price=p,
            best_ask_qty=10.0,
            event_time=self.latest_tick.get('received_at', now_dt),
            provider='DETRADE_SYNTHETIC',
        )
        bars = tuple(self.bar_aggregator.get_closed_bars(limit=60))
        last_bar = self.bar_aggregator.get_last_closed_bar()
        metrics = self.bar_aggregator.get_metrics()
        ticks = tuple(self._recent_ticks)
        return MicrostructureSnapshot(
            symbol=symbol.upper(),
            book_ticker=book,
            depth=None,
            recent_ticks=ticks,
            book_ticker_age_seconds=age,
            depth_age_seconds=None,
            is_fresh=True,
            last_5s_bar=last_bar,
            bars_5s=bars,
            bar_metrics_5s=metrics,
        )

    async def start(self) -> None:
        if not settings.detrade_ws_enabled:
            return
        if self._task and not self._task.done():
            return
        if settings.detrade_use_synthetic_feed:
            asyncio.create_task(self.bootstrap_history(120))
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

    @classmethod
    def _find_kline_payload(cls, value: Any, depth: int = 0) -> list[dict[str, Any]] | None:
        if depth > 8:
            return None
        if isinstance(value, dict):
            route = str(value.get('cmd', '')) or str(value.get('resp', ''))
            if '/kline/' in route:
                payload = value.get('data') if value.get('data') is not None else value.get('resp')
                if payload is None:
                    payload = value.get('payload')
                if isinstance(payload, dict) and 'p' in payload and 't' in payload:
                    return [payload]
                if isinstance(payload, list):
                    valid = [x for x in payload if isinstance(x, dict) and 'p' in x and 't' in x]
                    if valid:
                        return valid
            if {'s', 't', 'p'} <= set(value):
                return [value]
            for key, nested in value.items():
                if any(secret in str(key).lower() for secret in ('token', 'cookie', 'authorization', 'session', 'jwt', 'accesscode')):
                    continue
                found = cls._find_kline_payload(nested, depth + 1)
                if found is not None:
                    return found
        elif isinstance(value, list):
            items = [x for x in value if isinstance(x, dict) and 'p' in x and 't' in x]
            if items:
                return items
            for nested in value:
                found = cls._find_kline_payload(nested, depth + 1)
                if found is not None:
                    return found
        return None

    async def _consume(self, decoded: Any) -> bool:
        if self._contains_auth_failure(decoded):
            await self.token_provider.invalidate()
            self._force_credential_refresh = True
            self.latest = None
            self.last_error = 'DeTrade authorization expired or requires refresh.'
            self._observation_event.set()
            return False

        # 1. Check for synthetic kline ticker updates
        kline_data = self._find_kline_payload(decoded)
        if kline_data is not None:
            for item in kline_data:
                try:
                    p = float(item['p'])
                    t = int(item['t'])
                    sym = str(item.get('s', settings.detrade_synthetic_symbol))
                    c = float(item['c']) if 'c' in item and item['c'] is not None else None
                    self.bar_aggregator.add_synthetic_tick(price=p, timestamp_ms=t)
                    now_utc = datetime.now(timezone.utc)
                    ts = (float(t) / 1000.0) if t > 1e11 else float(t)
                    ev_time = datetime.fromtimestamp(ts, tz=timezone.utc) if ts > 0 else now_utc
                    self._recent_ticks.append(
                        MarketTick(
                            symbol=settings.analysis_pair,
                            price=p,
                            quantity=1.0,
                            event_time=ev_time,
                            provider='DETRADE_SYNTHETIC',
                            is_buyer_maker=False,
                        )
                    )
                    self.latest_tick = {
                        'price': p,
                        'timestamp_ms': t,
                        'symbol': sym,
                        'change': c,
                        'received_monotonic': time.monotonic(),
                        'received_at': now_utc,
                        'source': 'WS_STREAM',
                    }
                    self._last_tick_price = p
                    if self.on_tick is not None:
                        try:
                            res = self.on_tick(self.latest_tick)
                            if asyncio.iscoroutine(res):
                                await res
                        except Exception:
                            pass
                except (KeyError, ValueError, TypeError):
                    continue

        # 2. Check for authoritative round observation
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
        self._observation_event.set()
        if self.on_observation is not None:
            try:
                res = self.on_observation(self.latest)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                pass
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
                if settings.detrade_use_synthetic_feed:
                    await ws.send(self._encode_message(
                        self._authenticated_message(credentials, settings.detrade_kline_subscription_cmd)
                    ))
                heartbeat = asyncio.create_task(self._heartbeat(ws, credentials))
                try:
                    while not self._stop.is_set():
                        try:
                            frame = await asyncio.wait_for(
                                ws.recv(),
                                timeout=settings.detrade_ping_timeout_seconds,
                            )
                        except TimeoutError:
                            self.last_error = 'DeTrade round feed timed out.'
                            return None
                        try:
                            decoded = self._decode_frame(frame)
                        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                            self.last_error = 'A DeTrade frame could not be decoded.'
                            continue
                        if self._contains_auth_failure(decoded):
                            await self.token_provider.invalidate()
                            self._force_credential_refresh = True
                            self.latest = None
                            self.last_error = 'DeTrade authorization expired or requires refresh.'
                            self._observation_event.set()
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

        credentials = await self.token_provider.get_credentials(
            force_refresh=self._force_credential_refresh
        )
        if credentials is None:
            self.last_error = 'DeTrade authorization is not available yet.'
            return None
        self._force_credential_refresh = False

        timeout = timeout_seconds or settings.detrade_probe_timeout_seconds
        if self._task and not self._task.done():
            self._observation_event.clear()
            if self.latest and self.latest.fresh:
                return self.latest
            try:
                await asyncio.wait_for(self._observation_event.wait(), timeout=timeout)
            except TimeoutError:
                pass
            if self.latest and self.latest.fresh:
                return self.latest
            if self.last_error and 'authorization' in self.last_error.lower():
                return None
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
            credentials = await self.token_provider.get_credentials(
                force_refresh=self._force_credential_refresh
            )
            if credentials is None:
                self.last_error = 'DeTrade authorization is not available yet.'
                await asyncio.sleep(min(backoff, 5.0))
                backoff = min(backoff * 1.7, settings.detrade_reconnect_max_seconds)
                continue
            self._force_credential_refresh = False
            observation = await self._session(credentials, first_frame_only=False)
            if self._stop.is_set():
                return
            # A session that delivered a valid frame was healthy. Reset before
            # sleeping; after the sleep the 1.5s freshness window has naturally
            # elapsed and can no longer tell us whether that session succeeded.
            if observation is not None:
                backoff = max(1.0, settings.detrade_reconnect_seconds)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.7, settings.detrade_reconnect_max_seconds)


detrade_observer = DeTradeObserver()
