# Deployment Plan

## Target

Render is the V1 deployment platform.

## Services

1. **Web Service (Starter)** — Telegram webhook, onboarding/owner verification, on-demand manual countdown scans, health/readiness and lightweight external BTC feed.
2. **Background Worker (Starter)** — independent BTC feed, singleton lifecycle coordination, durable owner-packet delivery, future BC.GAME round integration, diagnostic lifecycle, broadcasts and retention cleanup.
3. **PostgreSQL 16** — persistent product state and worker heartbeat. The checked-in Blueprint currently uses Render Free PostgreSQL for initial deployment/testing. Free databases expire after 30 days and have no backups, so upgrade before relying on the database for valuable long-lived production history.
4. **Redis** — deferred until scale measurements justify it.

## Checked-in Controlled-Beta State

The Render Blueprint intentionally deploys the current MANUAL_SYNC beta as active:

```text
SIGNAL_MODE=LIVE
SIGNALS_ENABLED=true
BROADCASTS_ENABLED=true
SIGNAL_TIMING_MODE=MANUAL_SYNC
MANUAL_SYNC_ALLOWED_COUNTDOWNS=15,14,13,12
MANUAL_SYNC_MIN_REMAINING_AFTER_SCAN=7
BCGAME_ROUND_SYNC_ENABLED=false
```

LIVE is still fail-closed. An actionable direction is refused when user access, worker health, market freshness, sparse-data checks, countdown timing, cooldown, strategy health or other required gates fail.

`AUTO_SYNC` is not enabled and must not be fabricated. MANUAL_SYNC remains the V1 round-timing contract until a legitimate BC.GAME/DeTrade structured source is verified.

## Product Environment

```text
GAME_MARKET=BTC/USD
ANALYSIS_PAIR=BTCUSDT
DEFAULT_PAIR=BTCUSDT
DEFAULT_PRODUCT=BC_UPDOWN_5S
DEFAULT_EXPIRY_SECONDS=5
DEFAULT_STAKE_BAND=1-50
STRATEGY_VERSION=BTC_UPDOWN_5S_V1.1
SIGNAL_USER_COOLDOWN_SECONDS=5
SIGNAL_MIN_RECENT_TRADES=12
SIGNAL_MIN_TICK_SPAN_SECONDS=4
SIGNAL_SETTLEMENT_WINDOW_SECONDS=2
WORKER_HEARTBEAT_MAX_AGE_SECONDS=30
MARKET_CANDLE_MAX_AGE_SECONDS=60
VERIFICATION_MAX_DEPOSIT_PROOFS=3
```

Required secrets/links:

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_WEBHOOK_SECRET
OWNER_TELEGRAM_ID
BCGAME_REGISTRATION_URL
BCGAME_DEPOSIT_URL
BCGAME_UPDOWN_URL
SUPPORT_URL
```

Verification packets go directly to the owner's private Telegram conversation with the bot. There is no `ADMIN_CHAT_ID`.

## GitHub Actions Policy

GitHub Actions workflows are disabled at the owner's request because the monthly Actions allowance is unavailable. Do not re-enable or depend on Actions until the owner explicitly changes this instruction.

Validation path:

```text
repository review
→ Render build/pre-deploy migration
→ /health + /ready
→ Telegram onboarding/owner-review smoke test
→ controlled LIVE MANUAL_SYNC signal test
→ latency and external-reference result measurement
```

PAPER remains available as an explicit diagnostic mode, but it is not the checked-in Render deployment default.

## Deployment Gates

### Infrastructure gate

1. Render creates Web + Worker + PostgreSQL.
2. Alembic migrations succeed and reach `0007_security_delivery_hardening`.
3. Web boots.
4. Worker boots and heartbeat is fresh.
5. `/ready` confirms database connectivity.
6. `/health` reports LIVE, signals/broadcasts enabled by default, correct five-second product identity, fresh BTCUSDT reference data, fresh candle context and worker heartbeat.
7. `/market/status` labels BTCUSDT as external-reference-only.
8. Webhook rejects missing/incorrect secrets, non-JSON input and oversized bodies.

### Onboarding gate

1. New user sees registration flow, not main menu.
2. Registration → deposit → User ID → profile proof → deposit proof works.
3. Evidence survives restart.
4. The durable worker delivers the bounded complete verification packet to `OWNER_TELEGRAM_ID`; decision buttons appear only after evidence delivery succeeds.
5. Approve unlocks menu.
6. Resubmit preserves old reviewed packet and creates new evidence packet.
7. Reject/suspend/block are enforced backend-side.

### Five-second product gate

1. `SIGNAL_TIMING_MODE=MANUAL_SYNC` is active and only 15/14/13/12 callbacks are accepted.
2. Estimated Start/End timestamps remain explicitly labelled manual estimates and synthetic IDs never enter `bcgame_rounds`.
3. Worker heartbeat, tick data and candle context pass their freshness limits.
4. Human-action lead time is measured end-to-end and at least seven seconds remains after analysis.
5. Product remains BTC/USD, 5s, $1-50 V1 scope.
6. External Start/End tracking is diagnostic/reference-only; it must never be represented as official BC.GAME settlement truth.
7. Direction decisions are generated only from data available before the estimated Start Rate.
8. NO_TRADE and UNAVAILABLE remain distinct and are tested.
9. Current-signal serialization and user cooldown prevent duplicate actionable scans.
10. No automatic BC.GAME execution exists.

## PAPER Diagnostic Mode

If troubleshooting requires a non-actionable environment, the operator may explicitly set both services to:

```text
SIGNAL_MODE=PAPER
SIGNALS_ENABLED=false
BROADCASTS_ENABLED=false
```

PAPER must never show actionable execution instructions or an actionable BC.GAME trade button.

## Database

Keep core history: users, verification packets, strategy decisions, genuine BC.GAME round metadata/results when available, broadcast summaries and audit state.

Temporary technical records are cleaned after 10 days. Do not store continuous raw tick/order-book streams indefinitely in PostgreSQL. MANUAL_SYNC estimates stay with signal metadata and do not create fake official BC.GAME round rows.

## Stop Conditions

Stop signal delivery immediately when any of these occurs:

- worker heartbeat stale;
- market feed or candle context stale;
- insufficient recent trade density/tick span;
- manual countdown invalid, unconfirmed or too late;
- order window too close to closing;
- round/product/duration mismatch;
- unexpected strategy version;
- duplicate lifecycle/current-signal processing;
- user access changes during analysis;
- kill switch/signals switch is off;
- external reference data is being presented as BC.GAME settlement truth.
