# M11 — MANUAL_SYNC Controlled-Beta Validation Runbook

## Purpose

Validate the production topology and real BC.GAME Up/Down interaction contract without inventing provider data or making profit claims. The checked-in Render Blueprint targets **LIVE + MANUAL_SYNC** for a controlled beta. AUTO_SYNC remains unavailable until a verified structured BC.GAME/DeTrade source exists.

## Required checked-in state

```text
SIGNAL_MODE=LIVE
SIGNALS_ENABLED=true
BROADCASTS_ENABLED=true
SIGNAL_TIMING_MODE=MANUAL_SYNC
MANUAL_SYNC_ALLOWED_COUNTDOWNS=15,14,13,12
MANUAL_SYNC_MIN_REMAINING_AFTER_SCAN=7
BCGAME_ROUND_SYNC_ENABLED=false
```

## Phase A — Infrastructure and onboarding validation

Before asking beta users to act on signals, verify:

1. Web, worker and PostgreSQL start; Alembic reaches `0007_security_delivery_hardening`.
2. `/ready` confirms database connectivity.
3. `/health` reports LIVE, the five-second product, fresh BTCUSDT ticks, fresh candle context and worker heartbeat without raw exception text.
4. `/market/status` labels BTCUSDT external-reference-only.
5. The webhook rejects a missing/incorrect secret, non-JSON input and oversized bodies.
6. Registration → deposit → BC.GAME User ID → bounded screenshots creates a durable owner delivery.
7. Owner decisions are unavailable until all evidence is delivered; approve, reject and resubmit remain idempotent.
8. Suspended/blocked users cannot use stale callbacks or receive queued protected content.
9. Only approved users see the normal signal menu.

## Phase B — Controlled LIVE MANUAL_SYNC validation

For a small approved cohort, verify:

1. The user prepares BTC/USD, 5s and the $1-50 band/stake on BC.GAME before scanning.
2. Only 15s/14s/13s/12s callbacks are accepted.
3. Worker, tick and candle freshness fail closed as UNAVAILABLE.
4. Sparse/insufficient recent trade data fails closed rather than forcing a direction.
5. Too little remaining human-action time returns UNAVAILABLE and creates no actionable signal.
6. Sufficient but ambiguous evidence creates and records NO_TRADE.
7. A qualified direction is recorded before delivery and contains the correct BC.GAME Up/Down URL.
8. Concurrent callbacks cannot create two current signals for one user; cooldown prevents rapid duplicate scans.
9. MANUAL_SYNC synthetic timing stays in signal metadata and never enters `bcgame_rounds` as an official round.
10. Background external Start/End tracking remains reference-only and never reverses the delivered direction.
11. My Results labels external-reference WIN/LOSS/TIE explicitly.
12. No automatic BC.GAME trade placement, Martingale, loss chasing, guarantee or fabricated confidence exists.
13. Measure end-to-end Telegram latency and record whether 15s, 14s, 13s or 12s scan timing performs best; do not assume the optimal scan second without evidence.

## Optional PAPER diagnostic mode

If the operator needs a non-actionable troubleshooting mode, both Render services may be explicitly changed together to:

```text
SIGNAL_MODE=PAPER
SIGNALS_ENABLED=false
BROADCASTS_ENABLED=false
```

In PAPER mode there must be no actionable BC.GAME button or instruction to place a wager. Restore the checked-in LIVE MANUAL_SYNC state only after health/onboarding issues are resolved.

## AUTO_SYNC research boundary

`AUTO_SYNC` stays unavailable until a legitimate structured BC.GAME/DeTrade source is verified for genuine round ID, countdown/order close, Start/End times and product rates. The adapter boundary remains in place; do not fabricate an endpoint, credentials, responses or settlement values.

## Stop conditions

Stop LIVE signal delivery if worker/tick/candle health is stale, recent market data is too sparse, timing validation fails, the kill switch is off, authorization changes during analysis, strategy identity drifts, a direction arrives too late, external references are presented as BC.GAME truth, or duplicate current signals appear.
