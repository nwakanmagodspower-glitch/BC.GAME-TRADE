# Milestones — Five-Second Product Rebaseline

> Historical planning record. The active implementation now uses the verified DeTrade timer with `HYBRID_SYNC`. References below to `15s/14s/13s/12s`, My Results, or future timer discovery are superseded by `ARCHITECTURE.md`, `PRODUCT_SPEC.md`, and `DETRADE_AUTH_TIMER.md`; those buttons are not active.

The live BC.GAME Up/Down interface and supplied How to Trade instructions changed the trading contract from the earlier assumed 300-second model to the actual target: **BTC/USD, 5-second Start Rate → End Rate rounds**.

Infrastructure already built is retained. Old timing/backtest milestones are superseded where they conflict with this contract.

## M0 — Product Rules and Architecture — REBASELINED

- BTC/USD game display
- BTCUSDT external analysis feed initially
- 5-second duration
- `$1-50` initial stake band
- order countdown is separate from five-second measurement
- first flag = Start Rate
- second flag = End Rate
- manual execution only
- no guaranteed-win/Martingale behavior

**Exit:** permanent docs agree on the real game contract.

## M1 — Application / Database / Render Foundation — RETAIN

- FastAPI web service
- dedicated worker
- PostgreSQL + migrations
- config validation
- health/readiness
- Telegram webhook security
- worker heartbeat/advisory-lock protection
- 10-day temporary cleanup

**Exit:** deployable infrastructure runs safely with signals off.

## M2 — Verification Funnel — RETAIN

- guided registration/deposit flow
- User ID + profile screenshot + deposit screenshots
- packet sent directly to owner private bot chat
- approve/reject/resubmit
- resubmission history preservation
- approved user memory

**Exit:** onboarding works end to end without a separate admin group.

## M3 — Telegram Five-Second UX — DESIGNED

- `⚡ BTC 5s Signal`
- game explanation before scanning
- `15s` / `14s` / `13s` / `12s` countdown confirmation
- minimal UP/DOWN/NO_TRADE/UNAVAILABLE card
- result history
- How It Works
- Support

**Exit:** interface matches the real game mechanics and does not expose backend complexity.

## M4 — External High-Frequency Market Foundation — ACTIVE

- Binance trade stream
- 1s/3s/5s price velocity
- tick acceleration
- aggressive buy/sell flow
- micro-volatility
- slower candle context
- freshness checks

Next extensions after evidence:

- bid/ask spread
- order-book imbalance
- microprice
- cross-exchange confirmation

**Exit:** five-second feature snapshots are reproducible and fresh.

## M5 — BC.GAME Round/Data Discovery — FUTURE AUTO_SYNC GATE

Discover and validate a legitimate reliable structured source used by/available for the Up/Down page for as many of these as possible:

- round ID
- countdown/order-close timestamp
- Start Rate timestamp/value
- End Rate timestamp/value
- payout percentages
- pool amounts/player counts
- stake band

Do not use guessed minute timing. Do not make fragile screen scraping the permanent default if a structured source exists.

**Exit:** `BCGameRoundService` can return a fresh genuine AUTO_SYNC round and observed results reliably. This is not required for MANUAL_SYNC controlled beta.

## M6 — MANUAL_SYNC Signal Engine — IMPLEMENTED

- require the user's 15/14/13/12 confirmation during the BC.GAME order window
- enforce human-action lead time
- predict Start Rate → +5s End Rate direction
- recheck access, kill switch, data health and remaining time before persistence
- never reverse a delivered MANUAL_SYNC direction
- NO_TRADE weak rounds
- UNAVAILABLE bad data/round state

**Exit:** directional candidates are tied to an explicit user-confirmed timer estimate; synthetic timing is labelled and never stored as a genuine BC.GAME round.

## M7 — BC.GAME Outcome Labelling

- capture BC.GAME Start Rate / End Rate
- actual UP/DOWN label
- external reference start/end for comparison
- disagreement measurement
- immutable strategy/round evidence

**Exit:** model performance is measured against the game itself.

## M8 — Five-Second Research / Calibration

- enough real rounds across market regimes
- directional accuracy
- NO_TRADE rate
- unresolved rate
- timing/latency distribution
- feature ablation
- threshold/walk-forward calibration using sufficiently granular data

Old 1-minute-candle / 5-minute-expiry results are not evidence for this contract.

**Exit:** research shows whether a repeatable edge exists; no profitability claim is assumed.

## M9 — Payout / Expected-Value Research

Once reliable payout data exists:

- keep direction prediction separate from payout
- calculate whether displayed return is adequate for calibrated probability
- permit payout to veto a direction to NO_TRADE
- test pool/player data independently before using it

**Exit:** economic filtering is evidence-based rather than assumed.

## M10 — Render PAPER Deployment

- Web Starter
- Worker Starter
- Free PostgreSQL for PAPER validation only; paid PostgreSQL before controlled-beta users
- PAPER
- signals off by default
- broadcasts off by default
- AUTO_SYNC off; MANUAL_SYNC active
- smoke checks via Render/runtime, not GitHub Actions

**Exit:** stable deployment without actionable signals.

## M11 — Safe PAPER + Controlled MANUAL_SYNC Validation

- PAPER infrastructure/onboarding with user signals off
- explicit owner promotion to LIVE MANUAL_SYNC
- model decisions recorded before the estimated Start Rate
- external Start/End diagnostics labelled reference-only
- Telegram latency measurements
- no execution button/instruction

**Exit:** timing, fail-closed behavior and delivery are proven against observed five-second rounds without claiming exact BC.GAME settlement ingestion.

## M12 — Controlled LIVE Beta

Only after explicit owner approval and all earlier gates:

- round sync healthy
- measured signal quality
- enough human-action lead time
- LIVE presentation
- direct BC.GAME Up/Down link
- manual execution only
- small approved user cohort

**Exit:** stable manual beta; continue monitoring rather than claiming guaranteed performance.

## M13 — Scale / Refinement

Evidence-driven only:

- order-book/microprice
- better calibration
- payout EV gate
- shared Redis/cache if concurrency requires it
- additional stake bands

Additional coins, durations or BC.GAME products require explicit new scope.
