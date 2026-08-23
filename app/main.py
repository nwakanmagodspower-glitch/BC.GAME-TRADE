from contextlib import asynccontextmanager
import asyncio
import hmac
import json

from fastapi import FastAPI, Header, HTTPException, Request
from sqlalchemy import text
from telegram import Update

from app.bot.application import build_telegram_application
from app.core.config import get_settings
from app.core.database import SessionLocal, engine
from app.core.startup import validate_settings
from app.integrations.bcgame_rounds import bcgame_round_service
from app.integrations.detrade_observer import detrade_observer
from app.integrations.detrade_token_provider import usable_detrade_token
from app.services.background_coordinator import background_job_coordinator
from app.services.market_data import market_data_service
from app.services.retention_cleanup import retention_cleanup_service
from app.services.signal_intelligence import ENGINE_NAME, signal_intelligence_service
from app.services.signal_worker import signal_lifecycle_worker
from app.services.broadcast_worker import broadcast_worker
from app.services.verification_delivery_worker import verification_delivery_worker
from app.services.webhook_backpressure import telegram_update_user_id, webhook_backpressure
from app.services.webhook_receipts import WebhookReceiptService
from app.services.worker_status import get_worker_status

settings = get_settings()
startup_check = validate_settings(settings)
telegram_app = build_telegram_application()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not startup_check.ok:
        raise RuntimeError('Invalid application configuration: ' + '; '.join(startup_check.errors))
    await market_data_service.start(settings.analysis_pair)
    await detrade_observer.start()
    if settings.run_background_jobs:
        await background_job_coordinator.start()
    if telegram_app is not None:
        await telegram_app.initialize(); await telegram_app.start()
    try:
        yield
    finally:
        if telegram_app is not None:
            await telegram_app.stop(); await telegram_app.shutdown()
        if settings.run_background_jobs:
            await background_job_coordinator.stop()
        await detrade_observer.stop()
        await market_data_service.stop()


_production = settings.app_env.lower() == 'production'
app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url=None if _production else '/docs',
    redoc_url=None if _production else '/redoc',
    openapi_url=None if _production else '/openapi.json',
)


def _worker_heartbeat_status() -> dict:
    try:
        with SessionLocal() as db:
            status = get_worker_status(db)
            return {
                'seen': status.seen,
                'fresh': status.fresh,
                'healthy': status.healthy,
                'age_seconds': round(status.age_seconds, 3) if status.age_seconds is not None else None,
                'last_heartbeat': status.last_heartbeat,
                'components': status.components,
            }
    except Exception:
        return {
            'seen': False,
            'fresh': False,
            'healthy': False,
            'age_seconds': None,
            'last_heartbeat': None,
            'error_code': 'database_unavailable',
        }


@app.get('/health')
async def health():
    snapshot = await market_data_service.cache.get_snapshot(
        settings.analysis_pair,
        settings.market_data_max_age_seconds,
    )
    candles = await market_data_service.get_cached_candles(settings.analysis_pair)
    recent_trade_count, recent_trade_span = await market_data_service.cache.get_trade_window_metrics(
        settings.analysis_pair,
        settings.signal_trade_flow_lookback_seconds,
    )
    cleanup_result = retention_cleanup_service.last_result
    round_status = bcgame_round_service.status()
    observed = detrade_observer.latest
    candle_refresh_age = await market_data_service.cache.get_candle_refresh_age_seconds(
        settings.analysis_pair
    )

    return {
        'status': 'ok',
        'app': settings.app_name,
        'env': settings.app_env,
        'topology': 'combined' if settings.run_background_jobs else 'web-plus-dedicated-worker',
        'product': {
            'game_market': settings.game_market,
            'analysis_pair': settings.analysis_pair,
            'product': settings.default_product,
            'duration_seconds': settings.default_expiry_seconds,
            'stake_band': settings.default_stake_band,
            'strategy_version': ENGINE_NAME,
        },
        'signal_mode': settings.signal_mode,
        'signal_timing_mode': settings.signal_timing_mode,
        'manual_trigger': settings.signal_timing_mode.upper() == 'MANUAL_SYNC',
        'signals_enabled_default': settings.signals_enabled,
        'broadcasts_enabled_default': settings.broadcasts_enabled,
        'telegram_configured': bool(settings.telegram_bot_token),
        'startup_ok': startup_check.ok,
        'startup_warnings': startup_check.warnings,
        'round_sync': {
            'enabled': round_status.enabled,
            'seen': round_status.seen,
            'fresh': round_status.fresh,
            'age_seconds': round(round_status.age_seconds, 3) if round_status.age_seconds is not None else None,
            'round_id': round_status.round_id,
            'mode': 'manual_scan_now' if settings.signal_timing_mode.upper() == 'MANUAL_SYNC' else 'automatic',
            'error_code': 'round_sync_unavailable' if (not round_status.fresh and settings.signal_timing_mode.upper() != 'MANUAL_SYNC') else None,
        },
        'detrade_timer': {
            'enabled': settings.detrade_ws_enabled,
            'timing_only': True,
            'connected': detrade_observer.connected,
            'has_observation': observed is not None,
            'fresh': bool(observed and observed.fresh),
            'authorization_configured': usable_detrade_token(settings.detrade_ws_token) is not None,
            'timer': observed.to_public_dict() if observed else None,
            'error_code': 'observer_error' if detrade_observer.last_error and not (observed and observed.fresh) else None,
        },
        'market_data': {
            'provider': market_data_service.provider.name,
            'connected': market_data_service.connected,
            'fresh': bool(snapshot and snapshot.fresh),
            'age_seconds': round(snapshot.age_seconds, 3) if snapshot else None,
            'error_code': 'market_feed_unavailable' if market_data_service.last_error else None,
            'candle_cache_ready': bool(candles),
            'candle_cache_age_seconds': await market_data_service.cache.get_candle_age_seconds(settings.analysis_pair),
            'candle_refresh_age_seconds': (
                round(candle_refresh_age, 3) if candle_refresh_age is not None else None
            ),
            'candle_cache_error_code': 'candle_cache_unavailable' if market_data_service.candle_last_error else None,
            'recent_trade_count': recent_trade_count,
            'recent_trade_span_seconds': round(recent_trade_span, 3),
            'trade_flow_role': 'optional scoring evidence; not a hard readiness gate',
            'external_reference_only': True,
        },
        'prediction_engine': signal_intelligence_service.operational_status(),
        'dedicated_worker': _worker_heartbeat_status() if not settings.run_background_jobs else None,
        'background_jobs': {
            'local_to_web': settings.run_background_jobs,
            'leader': background_job_coordinator.is_leader if settings.run_background_jobs else False,
            'coordinator_error_code': 'coordinator_error' if (settings.run_background_jobs and background_job_coordinator.last_error) else None,
            'signal_worker_error_code': 'signal_worker_error' if (settings.run_background_jobs and signal_lifecycle_worker.last_error) else None,
            'broadcast_worker_error_code': 'broadcast_worker_error' if (settings.run_background_jobs and broadcast_worker.last_error) else None,
            'verification_worker_error_code': 'verification_worker_error' if (settings.run_background_jobs and verification_delivery_worker.last_error) else None,
            'cleanup_error_code': 'cleanup_error' if (settings.run_background_jobs and retention_cleanup_service.last_error) else None,
            'cleanup_last_run_at': retention_cleanup_service.last_run_at if settings.run_background_jobs else None,
            'cleanup_last_deleted': cleanup_result.total if (settings.run_background_jobs and cleanup_result) else None,
        },
    }


@app.get('/ready')
def ready():
    if not startup_check.ok:
        raise HTTPException(status_code=503, detail={'errors': startup_check.errors})
    try:
        with engine.connect() as connection:
            connection.execute(text('SELECT 1'))
    except Exception as exc:
        raise HTTPException(status_code=503, detail='database_unavailable') from exc
    return {'status': 'ready'}


@app.get('/market/status')
async def market_status():
    snapshot = await market_data_service.cache.get_snapshot(
        settings.analysis_pair,
        settings.market_data_max_age_seconds,
    )
    if snapshot is None:
        raise HTTPException(status_code=503, detail='market_data_unavailable')
    return {
        'game_market': settings.game_market,
        'analysis_symbol': snapshot.symbol,
        'price': snapshot.price,
        'event_time': snapshot.event_time,
        'provider': snapshot.provider,
        'age_seconds': round(snapshot.age_seconds, 3),
        'fresh': snapshot.fresh,
        'external_reference_only': True,
    }


@app.post('/telegram/webhook')
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if telegram_app is None:
        raise HTTPException(status_code=503, detail='telegram_not_configured')
    if not settings.telegram_webhook_secret:
        raise HTTPException(status_code=503, detail='telegram_webhook_secret_not_configured')
    if (
        not x_telegram_bot_api_secret_token
        or not hmac.compare_digest(x_telegram_bot_api_secret_token, settings.telegram_webhook_secret)
    ):
        raise HTTPException(status_code=403, detail='invalid_webhook_secret')

    content_type = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
    if content_type != 'application/json':
        raise HTTPException(status_code=415, detail='application_json_required')

    content_length = request.headers.get('content-length')
    if content_length:
        try:
            if int(content_length) > settings.telegram_webhook_max_body_bytes:
                raise HTTPException(status_code=413, detail='webhook_body_too_large')
        except ValueError as exc:
            raise HTTPException(status_code=400, detail='invalid_content_length') from exc

    body = await request.body()
    if len(body) > settings.telegram_webhook_max_body_bytes:
        raise HTTPException(status_code=413, detail='webhook_body_too_large')

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail='invalid_json') from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail='invalid_update')

    update_id = payload.get('update_id')
    if not isinstance(update_id, int):
        raise HTTPException(status_code=400, detail='invalid_update_id')

    user_id = telegram_update_user_id(payload)
    if not await webhook_backpressure.allow_user(user_id):
        raise HTTPException(status_code=429, detail='user_update_rate_limited')
    if not await webhook_backpressure.acquire():
        raise HTTPException(status_code=429, detail='webhook_capacity_busy')

    try:
        with SessionLocal() as db:
            claim = WebhookReceiptService(db).claim(update_id)
            if claim.duplicate:
                return {'ok': True, 'duplicate': True}
            if not claim.claimed:
                raise HTTPException(status_code=503, detail='update_already_processing')

        try:
            update = Update.de_json(payload, telegram_app.bot)
            await asyncio.wait_for(
                telegram_app.process_update(update),
                timeout=settings.telegram_update_processing_timeout_seconds,
            )
        except TimeoutError as exc:
            with SessionLocal() as db:
                WebhookReceiptService(db).fail(update_id, 'TimeoutError')
            raise HTTPException(status_code=503, detail='update_processing_timeout') from exc
        except Exception as exc:
            with SessionLocal() as db:
                WebhookReceiptService(db).fail(update_id, type(exc).__name__)
            raise HTTPException(status_code=503, detail='update_processing_failed') from exc

        with SessionLocal() as db:
            WebhookReceiptService(db).succeed(update_id)
        return {'ok': True}
    finally:
        webhook_backpressure.release()
