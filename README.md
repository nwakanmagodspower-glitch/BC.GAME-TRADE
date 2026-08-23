# BCGAME TRADE

Telegram signal assistant for the BCGAME BTC/USD 5-second Up/Down product and the `$1–$50` stake band. It analyzes external Binance Spot BTCUSDT data, never places trades, and never represents Binance prices as BCGAME settlement truth.

## Active engine

Strategy identity: **`BTC_ORIGINAL_INTELLIGENCE_TIMER_V1`**.

The direction engine is the restored original intelligence from before timer experiments. It uses:

- EMA 9 vs EMA 21
- five-minute momentum from closed 1-minute candles
- short-term higher-high/higher-low or lower-high/lower-low structure
- volume expansion and taker direction
- recent aggressive buy/sell trade flow when available
- RSI 14
- ATR 14 volatility quality adjustment

The decision policy is fixed at **minimum score 6 / minimum margin 3**. `NO_TRADE` remains a valid result.

## Intelligence and timer are separate

The prediction engine decides only `UP`, `DOWN`, or `NO_TRADE` from BTC market evidence.

The BC.GAME/DeTrade timer decides only whether the current BTC/USD five-second order window is safe to use. Countdown values do not change bull/bear scores, feature weights, thresholds, or direction.

## Production design

- FastAPI Telegram webhook service on Render
- dedicated Render background worker
- PostgreSQL with Alembic migrations
- shared Binance market stream/cache per process
- one shared DeTrade timing observer per web process
- `HYBRID_SYNC`: authoritative DeTrade timing when authorized; Scan Now fallback only when that timing source itself is unavailable
- approved-user access, owner verification, kill switches, broadcast controls, webhook backpressure, scan coalescing, and temporary-data cleanup

The normal user action is the permanent `⚡ BTC 5s Signal` button. The old `15s/14s/13s/12s` selector, My Result, Win/Loss calibration, V2 engine, cross-venue prediction voting, and 1s/3s/5s micro-return scoring are not active.

## Verified round timing

The authenticated browser investigation confirmed:

- WebSocket: `wss://websocket.detrade.com/ws`
- subscription: `/contest/BTC/USD/5/ticker/subscribe`
- authoritative betting boundary: `priceStartTime`
- countdown: `priceStartTime - (currentTime + local monotonic elapsed time)`
- actionable status: `1001` only
- evaluation window: `priceEndTime - priceStartTime ≈ 5000 ms`
- application frames: zlib-wrapped JSON; the decoder also safely accepts plain JSON and raw DEFLATE

Unknown, stale, late, non-`1001`, cancelled, transition, payout, finished, and wrong-duration rounds fail closed. A synchronized response that says a round is unsafe is never bypassed by HYBRID fallback.

See `docs/DETRADE_AUTH_TIMER.md` for the redacted protocol record and authorization limitation.

## Authorization boundary

The DeTrade token is an ephemeral secret created through the logged-in BCGAME browser flow. No verified unattended server-to-server BCGAME credential or refresh grant is assumed. A real token is accepted only from `DETRADE_WS_TOKEN` and is kept out of logs, health output, Telegram, source, and the database.

In `HYBRID_SYNC`, missing or expired authorization leaves the bot operational through manual Scan Now fallback. `AUTO_SYNC` requires usable authorization.

## Safe local setup

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt -r requirements-dev.txt
copy .env.example .env
alembic upgrade head
pytest -q
uvicorn app.main:app --reload
```

Local defaults are PAPER mode, signals off, broadcasts off, `MANUAL_SYNC`, and DeTrade disabled. Render production explicitly overrides timing to `HYBRID_SYNC`.

## Deployment

`render.yaml` preserves the existing `bcgame-trade-api`, `bcgame-trade-worker`, and `bcgame-trade-db` resources. Auto-deploy remains tied to `main`. Values marked `sync: false` are private and user-supplied.

Before enabling or trusting LIVE behavior, verify Render build, migration, `/ready`, `/health`, Telegram webhook delivery, Binance freshness, and the current DeTrade timing state.
