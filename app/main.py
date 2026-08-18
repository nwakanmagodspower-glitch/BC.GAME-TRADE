from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from sqlalchemy import text
from telegram import Update

from app.bot.application import build_telegram_application
from app.core.config import get_settings
from app.core.database import SessionLocal, engine
from app.core.startup import validate_settings
from app.services.market_data import market_data_service
from app.services.webhook_receipts import WebhookReceiptService

settings = get_settings()
startup_check = validate_settings(settings)
telegram_app = build_telegram_application()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Web keeps a lightweight shared market snapshot for on-demand scan requests.
    # Delayed lifecycle/settlement and broadcasts run only in app.worker on Render.
    await market_data_service.start(settings.default_pair)
    if telegram_app is not None:
        await telegram_app.initialize(); await telegram_app.start()
    try:
        yield
    finally:
        await market_data_service.stop()
        if telegram_app is not None:
            await telegram_app.stop(); await telegram_app.shutdown()


app = FastAPI(title=settings.app_name, lifespan=lifespan)


@app.get('/health')
async def health():
    snapshot = await market_data_service.cache.get_snapshot(settings.default_pair, settings.market_data_max_age_seconds)
    return {'status': 'ok', 'app': settings.app_name, 'env': settings.app_env, 'signal_mode': settings.signal_mode,
            'signals_enabled_default': settings.signals_enabled, 'telegram_configured': bool(settings.telegram_bot_token),
            'startup_ok': startup_check.ok, 'startup_warnings': startup_check.warnings,
            'market_data': {'provider': market_data_service.provider.name, 'connected': market_data_service.connected,
                            'fresh': bool(snapshot and snapshot.fresh), 'age_seconds': round(snapshot.age_seconds, 3) if snapshot else None,
                            'last_error': market_data_service.last_error}}


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
