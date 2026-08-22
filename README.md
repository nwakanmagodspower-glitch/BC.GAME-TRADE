# BCGAME TRADE

Telegram signal assistant for the BCGAME BTC/USD 5-second Up/Down product and the `$1–$50` stake band. It analyzes an external BTCUSDT market feed, but it never places trades and never represents Binance prices as BCGAME settlement truth.

## Current production design

- FastAPI Telegram webhook service on Render
- dedicated Render background worker
- PostgreSQL with Alembic migrations
- one shared Binance stream/cache per process
- one shared read-only DeTrade observer per web process
- `HYBRID_SYNC`: authoritative DeTrade timing when authorized, Scan Now fallback only when that source is unavailable
- approved-user access, owner verification, broadcast controls, webhook backpressure, scan coalescing, and ten-day temporary-data cleanup

The normal user action is the permanent `⚡ BTC 5s Signal` button. The old `15s/14s/13s/12s`, My Result, and Win/Loss calibration buttons are not part of the active UI.

## Verified round timing

The authenticated browser investigation confirmed:

- WebSocket: `wss://websocket.detrade.com/ws`
- subscription: `/contest/BTC/USD/5/ticker/subscribe`
- authoritative betting boundary: `priceStartTime`
- countdown: `priceStartTime - (currentTime + local monotonic elapsed time)`
- actionable status: `1001` only
- evaluation window: `priceEndTime - priceStartTime ≈ 5000 ms`
- application frames: zlib-wrapped JSON; the decoder also safely accepts plain JSON and raw DEFLATE

Unknown, stale, late, non-`1001`, `1008`, and wrong-duration rounds fail closed. A successful authoritative response that says the round is unsafe is never bypassed by HYBRID fallback.

See [DeTrade authorization and timer](docs/DETRADE_AUTH_TIMER.md) for the redacted protocol record and the exact remaining authorization limitation.

## Authorization boundary

The DeTrade token is an ephemeral secret created through the logged-in BCGAME browser flow. No verified unattended server-to-server BCGAME credential or refresh grant was found, so this repository deliberately does not guess one. The current safe provider accepts a real token only from `DETRADE_WS_TOKEN`, keeps it out of logs, health output, Telegram, source, and the database, and invalidates it after DeTrade auth failure. Rotation of that Render secret restarts the service.

`temporary`, `placeholder`, empty values, and related markers are never treated as authorization. In `HYBRID_SYNC`, missing or expired authorization leaves the bot operational in manual Scan Now fallback. `AUTO_SYNC` refuses to start without usable authorization.

## Local setup

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt -r requirements-dev.txt
copy .env.example .env
alembic upgrade head
pytest -q
uvicorn app.main:app --reload
```

Keep `.env` private. Safe defaults are PAPER mode, signals off, broadcasts off, and DeTrade disabled.

## Deployment

`render.yaml` preserves the existing `bcgame-trade-api`, `bcgame-trade-worker`, and `bcgame-trade-db` resources. Auto-deploy remains tied to `main`. Render values marked `sync: false` are private and user-supplied; a real `DETRADE_WS_TOKEN` is optional for HYBRID operation but required to activate synchronized timing.

Run the checks in [Render deployment checklist](docs/RENDER_DEPLOY_CHECKLIST.md) before enabling LIVE signals.
