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
from app.services.cross_venue_microstructure import cross_venue_microstructure_service
from app.services.market_data import market_data_service
from app.services.retention_cleanup import retention_cleanup_service
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
    await cross_venue_microstructure_service.start()
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
        await cross_venue_microstructure_service.stop()
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
    round_status = bcgame_round_service.status()
    cross = cross_venue_microstructure_service.snapshot()
    return {
        'status': 'ok',
        'market_data': {
            'connected': market_data_service.connected,
            'fresh': bool(snapshot and snapshot.fresh),
            'last_error': market_data_service.last_error,
        },
        'cross_venue': {
            'enabled': settings.cross_venue_enabled,
            'fresh': cross.fresh,
            'consensus': cross.consensus,
            'healthy_spread': cross.healthy_spread,
        },
        'bcgame_round_sync': {
            'enabled': round_status.enabled,
            'seen': round_status.seen,
            'fresh': round_status.fresh,
            'age_seconds': round_status.age_seconds,
            'round_id': round_status.round_id,
            'last_error': round_status.last_error,
        },
        'detrade': {
            'enabled': settings.detrade_ws_enabled,
            'token_configured': usable_detrade_token(settings.detrade_ws_token) is not None,
            'connected': detrade_observer.connected,
            'last_error': detrade_observer.last_error,
        },
        'worker': _worker_heartbeat_status(),
    }


@app.get('/')
async def root():
    return {'service': settings.app_name, 'status': 'ok'}


@app.post('/telegram/webhook')
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if telegram_app is None:
        raise HTTPException(status_code=503, detail='Telegram bot is not configured.')
    if settings.telegram_webhook_secret and not hmac.compare_digest(
        x_telegram_bot_api_secret_token or '', settings.telegram_webhook_secret
    ):
        raise HTTPException(status_code=403, detail='Invalid webhook secret.')

    body = await request.body()
    if len(body) > settings.telegram_webhook_max_body_bytes:
        raise HTTPException(status_code=413, detail='Webhook body too large.')
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail='Invalid JSON.') from exc

    user_id = telegram_update_user_id(payload)
    permit = await webhook_backpressure.acquire(user_id)
    if permit is None:
        raise HTTPException(status_code=429, detail='Too many requests.')
    try:
        update_id = payload.get('update_id')
        if isinstance(update_id, int):
            with SessionLocal() as db:
                receipt = WebhookReceiptService(db)
                if not receipt.claim(update_id):
                    return {'ok': True, 'duplicate': True}
        update = Update.de_json(payload, telegram_app.bot)
        await asyncio.wait_for(
            telegram_app.process_update(update),
            timeout=settings.telegram_update_processing_timeout_seconds,
        )
        return {'ok': True}
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail='Update processing timed out.') from exc
    finally:
        webhook_backpressure.release(permit)


@app.get('/internal/db-check')
async def db_check():
    if _production:
        raise HTTPException(status_code=404, detail='Not found.')
    with engine.connect() as connection:
        value = connection.execute(text('SELECT 1')).scalar()
    return {'ok': value == 1}
