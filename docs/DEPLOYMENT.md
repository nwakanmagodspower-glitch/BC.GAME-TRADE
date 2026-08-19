# Deployment Plan

## Target

Render is the V1 deployment platform.

## Services

1. **Web Service (Starter)** — Telegram webhook, onboarding/owner verification, on-demand manual countdown scans, health/readiness and lightweight external BTC feed.
2. **Background Worker (Starter)** — independent BTC feed, singleton lifecycle coordination, durable owner-packet delivery, future BC.GAME round integration, diagnostic lifecycle, broadcasts and retention cleanup.
3. **PostgreSQL** — persistent product state and worker heartbeat. First PAPER/research validation may use Render Free PostgreSQL. Free databases expire after 30 days and have no backups, so upgrade the same database to at least `basic-256mb` before admitting controlled-beta users.
4. **Redis** — deferred.

## Safe First Deployment

The initial deployment is intentionally non-actionable:

```text
SIGNAL_MODE=PAPER
SIGNALS_ENABLED=false
BROADCASTS_ENABLED=false
BCGAME_ROUND_SYNC_ENABLED=false
```

This means the infrastructure/onboarding can be deployed and tested without pretending the old minute-based timing matches BC.GAME.

## Product Environment

```text
GAME_MARKET=BTC/USD
ANALYSIS_PAIR=BTCUSDT
DEFAULT_PAIR=BTCUSDT
DEFAULT_PRODUCT=BC_UPDOWN_5S
DEFAULT_EXPIRY_SECONDS=5
DEFAULT_STAKE_BAND=1-50
STRATEGY_VERSION=BTC_UPDOWN_5S_V1.1
SIGNAL_TIMING_MODE=MANUAL_SYNC
MANUAL_SYNC_ALLOWED_COUNTDOWNS=15,14,13,12
MANUAL_SYNC_MIN_REMAINING_AFTER_SCAN=7
BCGAME_ROUND_SYNC_ENABLED=false
BCGAME_ROUND_SYNC_MAX_AGE_SECONDS=2
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
→ Telegram smoke tests
→ controlled PAPER round validation
```

## Deployment Gates

### Infrastructure gate

1. Render creates Web + Worker + PostgreSQL.
2. Alembic migrations succeed.
3. Web boots.
4. Worker boots and heartbeat is fresh.
5. `/ready` confirms database connectivity.
6. `/health` shows PAPER, signals off, fresh external BTC data and worker heartbeat.
7. webhook rejects requests without Telegram secret.

### Onboarding gate

1. New user sees registration flow, not main menu.
2. Registration → deposit → User ID → profile proof → deposit proof works.
3. Evidence survives restart.
4. The durable worker delivers the bounded complete verification packet to `OWNER_TELEGRAM_ID`; decision buttons appear only after evidence delivery succeeds.
5. Approve unlocks menu.
6. Resubmit preserves old reviewed packet and creates new evidence packet.
7. Reject/suspend/block are enforced backend-side.

### Five-second product gate

Before actionable signal mode:

1. `SIGNAL_TIMING_MODE=MANUAL_SYNC` is active and only 15/14/13/12 callbacks are accepted.
2. Estimated Start/End timestamps remain explicitly labelled manual estimates and synthetic IDs never enter `bcgame_rounds`.
3. Worker heartbeat, tick data and candle context pass their freshness limits.
4. Human-action lead-time is measured end-to-end and at least seven seconds remains after analysis.
5. Product is BTC/USD, 5s, approved V1 stake band.
6. External Start/End tracking is labelled diagnostic; the user checks the actual BC.GAME result.
7. Direction decisions are generated from data available before Start Rate.
8. NO_TRADE/UNAVAILABLE behavior is verified.
9. PAPER and LIVE renderings are verified as non-actionable and actionable respectively.

`BCGAME_ROUND_SYNC_ENABLED` remains false in MANUAL_SYNC. A future AUTO_SYNC promotion has a separate gate: a verified structured provider must supply genuine round/timing/result data.

## PAPER Validation

The default PAPER deployment validates infrastructure, onboarding and fail-closed controls. User-facing scans remain disabled. Offline or owner-controlled research may collect model decisions, but:

- no `ENTER NOW`;
- no actionable BC.GAME button;
- no claim that external reference result equals BC.GAME result;
- record BC.GAME Start/End Rate whenever trustworthy ingestion is available;
- use unresolved status rather than guessing missing results.

## LIVE Gate

LIVE requires all of the following simultaneously:

- MANUAL_SYNC timer buttons and post-computation lead-time rejection verified;
- enough measured technical/strategy evidence for the controlled cohort;
- strategy version explicitly approved;
- no fabricated confidence percentage;
- signal kill switch intentionally enabled;
- latency leaves enough time for manual execution;
- direct BC.GAME link points to the actual Up/Down page;
- no automatic trade placement.

## Database

Keep core history: users, verification packets, strategy decisions, BC.GAME round metadata/results, broadcast summaries, audit state.

Temporary technical records are cleaned after 10 days. Do not store continuous raw tick/order-book streams indefinitely in PostgreSQL.

## Stop Conditions

Stop signal delivery immediately when any of these occurs:

- worker heartbeat stale;
- market feed stale;
- manual countdown invalid, unconfirmed, or too late (or future AUTO_SYNC stale/missing);
- order window too close to closing;
- round/product/duration mismatch;
- unexpected strategy version;
- duplicate lifecycle processing;
- BC.GAME Start/End Rate cannot be trusted;
- PAPER presentation becomes actionable;
- kill switch is off.
