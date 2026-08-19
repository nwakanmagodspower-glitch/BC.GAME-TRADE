# M11 — MANUAL_SYNC Validation Runbook

## Purpose

Validate the production topology and the real BC.GAME Up/Down interaction contract without inventing provider data or making profit claims. The checked-in deployment starts in PAPER with user signals disabled. Controlled LIVE MANUAL_SYNC is a separate explicit promotion.

## Phase A — Safe PAPER deployment

Required state:

```text
SIGNAL_MODE=PAPER
SIGNALS_ENABLED=false
BROADCASTS_ENABLED=false
SIGNAL_TIMING_MODE=MANUAL_SYNC
BCGAME_ROUND_SYNC_ENABLED=false
```

Verify:

1. Web, worker and PostgreSQL start; Alembic reaches `0007_security_delivery_hardening`.
2. `/ready` confirms database connectivity.
3. `/health` reports the five-second product, fresh BTCUSDT ticks, fresh candle context and worker heartbeat without raw exception text.
4. The webhook rejects a missing/incorrect secret, non-JSON input and oversized bodies.
5. Registration → deposit → BC.GAME User ID → bounded screenshots creates a durable owner delivery.
6. Owner decisions are unavailable until all evidence is delivered; approve, reject and resubmit remain idempotent.
7. Approved users see the menu, but scan attempts state that PAPER is non-actionable.
8. Suspended/blocked users cannot use stale callbacks or receive queued protected content.

## Phase B — Controlled LIVE MANUAL_SYNC

Only after Phase A and explicit owner approval, change both Render services consistently:

```text
SIGNAL_MODE=LIVE
SIGNALS_ENABLED=true
BROADCASTS_ENABLED=true
```

Keep:

```text
SIGNAL_TIMING_MODE=MANUAL_SYNC
MANUAL_SYNC_ALLOWED_COUNTDOWNS=15,14,13,12
MANUAL_SYNC_MIN_REMAINING_AFTER_SCAN=7
BCGAME_ROUND_SYNC_ENABLED=false
```

For a small approved cohort, verify:

1. The user prepares BTC/USD, 5s and the $1-50 band on BC.GAME before scanning.
2. Only 15s/14s/13s/12s callbacks are accepted.
3. Worker, tick and candle freshness fail closed as UNAVAILABLE.
4. Too little remaining human-action time returns UNAVAILABLE and creates no actionable signal.
5. Sufficient but ambiguous evidence creates and records NO_TRADE.
6. A qualified direction is recorded before delivery and contains the correct BC.GAME Up/Down URL.
7. Concurrent callbacks cannot create two current signals for one user.
8. MANUAL_SYNC synthetic IDs remain in signal metadata and never enter `bcgame_rounds`.
9. Background external Start/End tracking remains reference-only and never reverses the delivered direction.
10. My Results labels external-reference WIN/LOSS/TIE explicitly.
11. No automatic BC.GAME trade placement, Martingale, loss chasing, guarantee or fabricated confidence exists.

## AUTO_SYNC research boundary

`AUTO_SYNC` stays unavailable until a legitimate structured BC.GAME/DeTrade source is verified for genuine round ID, countdown/order close, Start/End times and product rates. The adapter boundary remains in place; do not fabricate an endpoint, credentials, responses or settlement values.

## Stop conditions

Stop LIVE signal delivery if worker/tick/candle health is stale, timing validation fails, the kill switch is off, authorization changes during analysis, the strategy identity drifts, a direction arrives too late, external references are presented as BC.GAME truth, or duplicate current signals appear.
