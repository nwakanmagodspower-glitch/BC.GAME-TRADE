# M11 — Five-Second PAPER Round Validation

## Purpose

Demonstrate that the redesigned system follows the actual BC.GAME Up/Down round: order countdown → Start Rate → 5 seconds → End Rate. PAPER validation proves technical correctness and measures strategy behavior; it does not guarantee profit or authorize automated trading.

## Required starting state

- Render Web + Worker + PostgreSQL healthy.
- `SIGNAL_MODE=PAPER`.
- deployment defaults: signals OFF, broadcasts OFF.
- product: `BTC/USD`, `BC_UPDOWN_5S`, 5 seconds, `$1-50` band.
- external analysis: BTCUSDT.
- onboarding/owner verification smoke-tested.
- BC.GAME round provider integrated and measured before controlled round signals are enabled.

## Phase A — Infrastructure Before Round Sync

With `BCGAME_ROUND_SYNC_ENABLED=false` verify:

1. Web/worker boot safely.
2. `/health` reports the five-second product contract.
3. `/health` shows round sync disabled.
4. an approved user's `Scan Next Round` does **not** invent timing and returns unavailable.
5. no LIVE button or `ENTER NOW` message exists.

This phase may be deployed before round discovery is complete.

## Phase B — Round Synchronization

After a legitimate structured round source is integrated:

For at least multiple consecutive observed rounds, compare backend data with the visible BC.GAME interface:

- round/countdown state;
- order-close timestamp;
- first-flag Start Rate time/value;
- second-flag End Rate time/value;
- duration = 5s;
- stake band;
- UP/DOWN payout where available;
- pool/player counts where available.

Do not enable user-facing round signals until timing is consistently aligned.

## Phase C — Controlled Model Decisions

For approved test users only:

1. Request `⚡ BTC 5s Signal`.
2. Tap `Scan Next Round`.
3. Only evaluate when order-close is inside the configured action window (initially 5-10 seconds away).
4. Record external tick features and model decision before Start Rate.
5. Direction may be UP, DOWN or NO_TRADE.
6. Provider/timing failure must be UNAVAILABLE.
7. At Start Rate, record the BC.GAME value when available plus external diagnostic reference.
8. Five seconds later, record BC.GAME End Rate plus external diagnostic reference.
9. Actual product label comes from BC.GAME Start/End Rate.

## Required Evidence Per Round

- round ID;
- scan timestamp;
- seconds remaining when signal was delivered;
- Telegram delivery latency where measurable;
- strategy version;
- tick/trade-flow feature snapshot;
- model direction/quality;
- BC.GAME Start Rate / End Rate;
- actual direction;
- external start/end references;
- payout/pool metadata if available;
- final match/mismatch/unresolved state.

## Core Pass Conditions

- no signal uses guessed minute boundaries;
- no direction is delivered outside the configured action window;
- stale market or round data fails closed;
- Start Rate and End Rate align with BC.GAME observations;
- model uses only pre-Start-Rate data;
- no late `ENTER NOW` notification is emitted after the round locks;
- worker restart/deploy does not duplicate lifecycle processing;
- PAPER messages remain non-actionable;
- unresolved data is not converted into a fake WIN/LOSS;
- external price differences from BC.GAME are measured explicitly.

## Strategy Evaluation

Do not judge the five-second model using the old one-minute / five-minute backtest. Evaluate against actual five-second BC.GAME-labelled rounds and sufficiently granular historical/live data.

Track:

- UP/DOWN accuracy;
- NO_TRADE rate;
- UNAVAILABLE rate;
- skipped-too-early / skipped-too-late rounds;
- performance by micro-volatility;
- trade-flow strength;
- action lead time;
- payout band;
- external-vs-BC.GAME disagreement.

A small strong sample is not enough.

## Stop Conditions

Disable controlled signal testing immediately if:

- round sync drifts;
- Start/End Rate does not match BC.GAME;
- Telegram delivery leaves insufficient execution time;
- stale data produces a direction;
- late messages encourage entry after order lock;
- unapproved users can scan;
- PAPER shows an execution button;
- strategy/product/duration changes unexpectedly.

## LIVE Gate

Controlled LIVE beta requires explicit owner approval after enough five-second PAPER evidence. Manual user execution remains mandatory.
