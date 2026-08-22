# Render Deployment Checklist

## Before merge/deploy

- [ ] `pytest -q` passes locally.
- [ ] Python compile/parse check passes.
- [ ] `git diff --check` passes.
- [ ] Alembic upgrade from empty SQLite succeeds.
- [ ] Alembic downgrade/upgrade round trip succeeds.
- [ ] `alembic check` reports no model drift.
- [ ] `render.yaml` parses as YAML and retains exactly one web, worker, and database.
- [ ] Secret scan finds no credential values or token-bearing WebSocket URLs.

## Render configuration

- [ ] Existing services are `bcgame-trade-api` and `bcgame-trade-worker`.
- [ ] Existing database is `bcgame-trade-db`.
- [ ] Auto-deploy remains `main`/commit.
- [ ] Telegram token, webhook secret, and owner ID are populated privately.
- [ ] BCGAME registration, deposit, Up/Down, and support URLs are correct.
- [ ] No literal `temporary` or real DeTrade token exists in the Blueprint.
- [ ] If synchronized timing is desired now, put the current ephemeral token only in the private `DETRADE_WS_TOKEN` value.

## Post-deploy health

- [ ] `/ready` returns ready and the migration completed.
- [ ] `/health` reports PostgreSQL/market/worker health without secrets or exception text.
- [ ] owner sends `/round_status`; with a valid token it shows a real round ID, status, remaining time, approximately 5.000s evaluation window, and no credential.
- [ ] with no token, HYBRID remains healthy and `/round_status` reports authorization unavailable.
- [ ] known status `1008`, unknown status, stale frame, late round, and wrong-duration frame cannot produce a synchronized signal.

## Telegram journey

- [ ] `/start` onboarding is gated until owner approval.
- [ ] registration → deposit → BCGAME ID → profile screenshot → deposit screenshot → submit works.
- [ ] owner receives one media packet and one approve/reject/resubmit review block.
- [ ] decision purges BCGAME ID and Telegram file IDs while retaining approval state.
- [ ] permanent menu contains `⚡ BTC 5s Signal`, How It Works, and Support.
- [ ] there are no `15s/14s/13s/12s`, My Result, or Win/Loss calibration buttons.
- [ ] synchronized signal is compact and shows round/timing context without authorization.
- [ ] no automatic trade is placed.

## Operations

- [ ] dedicated worker heartbeat is fresh before enabling LIVE signals.
- [ ] ten-day cleanup job records successful runs.
- [ ] owner kill switch can disable signals.
- [ ] when DeTrade rejects authorization, replace the private token or accept HYBRID fallback; never reuse or log the rejected value.
