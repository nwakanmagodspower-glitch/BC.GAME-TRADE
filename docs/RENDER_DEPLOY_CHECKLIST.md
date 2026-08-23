# Render Deployment Checklist

## Before deploy

- [ ] `pytest -q` passes locally.
- [ ] Python compile/parse check passes.
- [ ] `git diff --check` passes.
- [ ] Alembic upgrade succeeds.
- [ ] `alembic check` reports no model drift.
- [ ] `render.yaml` parses and retains exactly one web service, one worker, and one database.
- [ ] Secret scan finds no credential values or token-bearing URLs.
- [ ] Active strategy identity is exactly `BTC_ORIGINAL_INTELLIGENCE_TIMER_V1`.
- [ ] Active thresholds are exactly score `6` / margin `3`.
- [ ] Active `app/signals/` contains only the restored feature/scoring/decision path; no V2 or cross-venue prediction engine is active.

## Render configuration

- [ ] Web service is `bcgame-trade-api`.
- [ ] Worker is `bcgame-trade-worker`.
- [ ] Database is `bcgame-trade-db`.
- [ ] Auto-deploy remains `main` / commit.
- [ ] Production uses `SIGNAL_TIMING_MODE=HYBRID_SYNC` and `BCGAME_ROUND_SYNC_ENABLED=true`.
- [ ] Production uses `STRATEGY_VERSION=BTC_ORIGINAL_INTELLIGENCE_TIMER_V1`.
- [ ] Production uses `SIGNAL_MIN_SCORE=6` and `SIGNAL_MIN_MARGIN=3`.
- [ ] Telegram token, webhook secret, owner ID, BCGAME URLs, and support URL are populated privately.
- [ ] No placeholder or real DeTrade token exists in source or Blueprint literals.
- [ ] A current ephemeral DeTrade token, when used, exists only in private `DETRADE_WS_TOKEN`.

## Post-deploy readiness

- [ ] Render build succeeds.
- [ ] Alembic pre-deploy migration succeeds.
- [ ] `/ready` returns `ready`.
- [ ] `/health` returns without exceptions and identifies `BTC_ORIGINAL_INTELLIGENCE_TIMER_V1`.
- [ ] `/health` shows Binance market freshness and labels recent trade flow as optional evidence, not a hard readiness gate.
- [ ] `/health` exposes no DeTrade credential.
- [ ] owner `/round_status` with a valid token shows a real round ID, status, remaining time, and approximately 5-second evaluation window.
- [ ] owner `/preflight` reports `READY TO SCAN` before any live recording; if it says `WAIT`, do not demonstrate an entry in that round.
- [ ] with no token, HYBRID remains operational through manual Scan Now fallback.
- [ ] status `1008`, unknown status, stale frame, late round, and wrong-duration frame cannot become a synchronized actionable round.

## Prediction regression

- [ ] bullish original context + flow can produce `UP`.
- [ ] bearish original context + flow can produce `DOWN`.
- [ ] neutral/conflicting evidence can produce `NO_TRADE`.
- [ ] timer metadata changes cannot alter direction, bull score, bear score, or margin.
- [ ] a wrong/late timer state rejects delivery without recalculating the prediction.
- [ ] no hard recent-trade-count or tick-span gate blocks the original engine.

## Telegram journey

- [ ] `/start` remains gated until owner approval.
- [ ] registration → deposit → BCGAME ID → profile screenshot → deposit proof → submit works.
- [ ] owner receives the verification packet and approve/reject/resubmit controls.
- [ ] permanent approved menu contains `⚡ BTC 5s Signal`, How It Works, and Support.
- [ ] there are no active `15s/14s/13s/12s`, My Result, Win/Loss calibration, or V2 controls.
- [ ] synchronized signal is compact and may show timing context without exposing authorization.
- [ ] no automatic trade is placed.

## Operations

- [ ] dedicated worker is healthy for lifecycle, broadcasts, verification delivery, and cleanup.
- [ ] worker health is not an artificial prediction gate for a healthy web scan.
- [ ] temporary-data cleanup records successful runs.
- [ ] owner kill switch can disable signals immediately.
- [ ] rejected/expired DeTrade authorization is replaced privately or HYBRID falls back; rejected credentials are never reused or logged.
