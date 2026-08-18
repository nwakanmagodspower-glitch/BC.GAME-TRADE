from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from sqlalchemy import text
from telegram import Update

from app.bot.application import build_telegram_application
from app.core.config import get_settings
from app.core.database import SessionLocal, engine
from app.core.startup import validate_settings
from app.services.background_coordinator import background_job_coordinator
from app.services.market_data import market_data_service
from app.services.retention_cleanup import retention_cleanup_service
from app.services.signal_worker import signal_lifecycle_worker
from app.services.broadcast_worker import broadcast_worker
from app.services.webhook_receipts import WebhookReceiptService

settings = get_settings()
startup_check = validate_settings(settings)
telegram_app = build_telegram_application()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail the deploy before any market feed, Telegram processing, or singleton
    # background job can start with an invalid production configuration.
    if not startup_check.ok:
        raise RuntimeError('Invalid application configuration: ' + '; '.join(startup_check.errors))

    await market_data_service.start(settings.default_pair)
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
        await market_data_service.stop()


app = FastAPI(title=settings.app_name, lifespan=lifespan)


@app.get('/health')
async def health():
    snapshot = await market_data_service.cache.get_snapshot(settings.default_pair, settings.market_data_max_age_seconds)
    cleanup_result = retention_cleanup_service.last_result
    return {
        'status': 'ok',
        'app': settings.app_name,
        'env': settings.app_env,
        'topology': 'combined' if settings.run_background_jobs else 'web-only',
        'signal_mode': settings.signal_mode,
        'signals_enabled_default': settings.signals_enabled,
        'broadcasts_enabled_default': settings.broadcasts_enabled,
        'telegram_configured': bool(settings.telegram_bot_token),
        'startup_ok': startup_check.ok,
        'startup_warnings': startup_check.warnings,
        'market_data': {
            'provider': market_data_service.provider.name,
            'connected': market_data_service.connected,
            'fresh': bool(snapshot and snapshot.fresh),
            'age_seconds': round(snapshot.age_seconds, 3) if snapshot else None,
            'last_error': market_data_service.last_error,
        },
        'background_jobs': {
            'enabled': settings.run_background_jobs,
            'leader': background_job_coordinator.is_leader if settings.run_background_jobs else False,
            'coordinator_error': background_job_coordinator.last_error,
            'signal_worker_error': signal_lifecycle_worker.last_error,
            'broadcast_worker_error': broadcast_worker.last_error,
            'cleanup_error': retention_cleanup_service.last_error,
            'cleanup_last_run_at': retention_cleanup_service.last_run_at,
            'cleanup_last_deleted': cleanup_result.total if cleanup_result else None,
        },
    }


@app.get('/ready')
def ready():
    if not startup_check.ok: raise HTTPException(status_code=503, detail={'errors': startup_check.errors})
    try:
        with engine.connect() as connection: connection.execute(text('SELECT 1'))
    except Exception as exc: raise HTTPException(status_code=503, detail='database_unavailable') from exc
    return {'status': 'ready'}


@app.get('/market/status')
async def market_status():
    snapshot = await market_data_service.cache.get_snapshot(settings.default_pair, settings.market_data_max_age_seconds)
    if snapshot is None: raise HTTPException(status_code=503, detail='market_data_unavailable')
    return {'symbol': snapshot.symbol, 'price': snapshot.price, 'event_time': snapshot.event_time, 'provider': snapshot.provider,
            'age_seconds': round(snapshot.age_seconds, 3), 'fresh': snapshot.fresh}


@app.post('/telegram/webhook')
async def telegram_webhook(request: Request, x_telegram_bot_api_secret_token: str | None = Header(default=None)):
    if telegram_app is None: raise HTTPException(status_code=503, detail='telegram_not_configured')
    if not settings.telegram_webhook_secret: raise HTTPException(status_code=503, detail='telegram_webhook_secret_not_configured')
    if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret: raise HTTPException(status_code=403, detail='invalid_webhook_secret')
    payload = await request.json(); update_id = payload.get('update_id')
    if not isinstance(update_id, int): raise HTTPException(status_code=400, detail='invalid_update_id')
    with SessionLocal() as db:
        if not WebhookReceiptService(db).claim(update_id): return {'ok': True, 'duplicate': True}
    update = Update.de_json(payload, telegram_app.bot); await telegram_app.process_update(update)
    return {'ok': True}
