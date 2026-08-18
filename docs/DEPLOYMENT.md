# Deployment Plan

## Deployment Target

Render is the production platform for V1.

## Services

1. **Web Service** — Telegram webhook, health endpoints, application API.
2. **Background Worker** — market feed upkeep, timed signal checks, settlement, broadcasts.
3. **PostgreSQL** — persistent application state.
4. **Optional Redis** — deferred until needed.

## Required Environment Variables

```text
APP_ENV=production
DATABASE_URL=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_WEBHOOK_SECRET=...
OWNER_TELEGRAM_ID=...
SIGNAL_MODE=PAPER
SIGNALS_ENABLED=false
DEFAULT_PAIR=BTCUSDT
DEFAULT_PRODUCT=BC_UPDOWN
DEFAULT_EXPIRY_SECONDS=300
STRATEGY_VERSION=BTC_UPDOWN_V1
BCGAME_AFFILIATE_URL=...
```

Secrets must live in Render, never GitHub.

## Required Endpoints

- `/health` — process alive
- `/ready` — database + critical dependencies ready
- `/telegram/webhook` — secret-protected Telegram webhook

## Deployment Gates

A release may progress only when all earlier gates pass:

1. App boots locally.
2. Configuration validation passes.
3. Database migrations apply cleanly.
4. Health/readiness endpoints pass.
5. Telegram webhook verifies correctly.
6. Guided onboarding works end to end.
7. Verification packet reaches admin correctly.
8. Admin decision persists and unlocks/blocks access correctly.
9. BTC market feed passes freshness checks.
10. Signal engine returns structured `UP/DOWN/NO_TRADE` decisions.
11. Exact timing/invalidation behavior works in paper mode.
12. Outcome settlement works.
13. Broadcast queue works without blocking signal requests.
14. Render deploy passes smoke tests.
15. Controlled paper-production run passes before live user signals.

## Production Modes

### `PAPER`

Real market data, real signal generation, outcomes tracked, but not presented as production trade recommendations.

### `LIVE`

Signals may be presented to approved users for manual execution. This still does **not** mean automated trade placement.

## Kill Switches

At minimum:

```text
SIGNALS_ENABLED=false
BROADCASTS_ENABLED=false
```

The owner must be able to disable signal delivery independently of Telegram onboarding and support.

## Deployment Safety

- Never deploy schema changes without migrations.
- Never expose a webhook without secret validation.
- Never mark service ready if database is unavailable.
- Never issue signals if market data freshness fails.
- Never activate live mode as part of an unrelated deployment.
- Roll forward with a new strategy version; do not mutate historical strategy identity.