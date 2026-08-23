# AGENTS.md

These rules govern every coding agent, developer, automation, and deployment change in this repository.

## Current Product Boundary

This repository has one product scope:

- BC.GAME Up/Down
- game display market: **BTC/USD**
- external analysis market: **BTCUSDT**
- duration: **5 seconds**
- stake band: **$1–$50**
- manual user execution only
- Telegram output: `UP`, `DOWN`, `NO_TRADE`, or `UNAVAILABLE`

Do not add other coins, products, durations, stake bands, automatic trade placement, Martingale, recovery logic, or money movement without an explicit owner instruction.

## Source of Truth — Prediction Core

The active prediction engine is **BTC_ORIGINAL_INTELLIGENCE_TIMER_V1**.

It intentionally restores the first pre-timer intelligence. Direction is calculated from:

- EMA 9 vs EMA 21 trend relationship
- five-minute momentum derived from closed 1-minute candles
- six-candle short-term market structure
- current 1-minute volume expansion and taker-buy ratio
- recent aggressive trade-flow buy/sell ratio when available
- RSI 14
- ATR 14 volatility quality adjustment

The decision rule is locked to:

- minimum directional score: **6**
- minimum winning margin over the opposite side: **3**
- `STRONG` only at score >= 8 and margin >= 4

`NO_TRADE` is a first-class outcome. Never lower these rules merely to increase signal frequency, and never raise them silently.

## Critical Separation — Intelligence vs Timer

The BC.GAME/DeTrade timer is **not part of prediction**.

Prediction answers only:

> What does the restored BTC intelligence currently say: UP, DOWN, or NO_TRADE?

Timing answers only:

> Is there a verified BC.GAME BTC/USD five-second order window with enough time for the user to act?

Therefore timing must never:

- add or subtract bull/bear score;
- change feature weights;
- change the 6/3 policy;
- convert UP to DOWN or DOWN to UP;
- add horizon-dependent prediction weights;
- add cross-exchange directional votes;
- force a new prediction merely because countdown metadata changed.

The same computed market result may be decorated with different timer metadata without changing direction or score.

## Timing Modes

### Local/default: MANUAL_SYNC

Safe development defaults use `MANUAL_SYNC`, PAPER mode, signals off, broadcasts off, and DeTrade disabled.

### Production: HYBRID_SYNC

Render production explicitly uses `HYBRID_SYNC`.

When a fresh authorized DeTrade frame is available:

- route: `/contest/BTC/USD/5/ticker/subscribe`
- actionable status: `1001`
- `priceStartTime` is the order-close / Start Rate boundary
- `priceEndTime - priceStartTime` must be about 5000 ms
- stale, late, unknown, cancelled, payout, transition, or wrong-duration frames fail closed
- initial synchronized entry requires more than the configured safety margin
- the timer is checked again after analysis before delivery

If an authoritative synchronized frame exists but says the round is unsafe, HYBRID must not bypass it. Manual fallback is allowed only when the authoritative source itself is unavailable.

## Market Data Rules

- Binance Spot BTCUSDT is the active external analysis feed.
- Binance prices are reference/analysis data, not BC.GAME settlement truth.
- Candle cache must contain enough closed candles for the original feature calculation.
- Recent aggressive trade flow is optional scoring evidence. Lack of a fixed trade count/span must not become a hard readiness gate.
- Do not reintroduce the removed 1s/3s/5s micro-return engine, cross-venue voting engine, V2 unified engine, horizon-aware scoring, or calibration engine unless the owner explicitly starts a separate research version.

## User Signal Flow

Approved user taps **⚡ BTC 5s Signal**.

1. Recheck user approval/block status and signal kill switch.
2. Resolve timing according to the configured timing mode.
3. Compute or reuse a very short-lived market prediction independently of timer values.
4. If synchronized, recheck remaining BC.GAME order-window time after analysis.
5. Persist the scan using strategy identity `BTC_ORIGINAL_INTELLIGENCE_TIMER_V1`.
6. Send the compact Telegram result.
7. User manually executes on BC.GAME if the round is still timely.

There is no active 15/14/13/12 selector UI, My Result button, Win/Loss calibration UI, or automatic order placement.

## Access and Operations

Preserve:

- owner/manual affiliate verification
- approved-user-only signal access
- owner block/suspend/kill-switch controls
- webhook secret verification
- webhook backpressure and update idempotency
- PostgreSQL persistence and migrations
- Render web + dedicated worker topology
- temporary-data cleanup
- secrets outside GitHub

Background-worker health may be reported and used for background lifecycle tasks, but it must not become an artificial hard gate on a healthy web-process signal scan unless a future architecture explicitly depends on that worker for required prediction data.

## Prohibited Regressions

Do not:

- restore `engine_v2`;
- restore cross-venue prediction voting;
- restore 1s/3s/5s micro-return scoring as the active engine;
- restore 8/4 production thresholds;
- make timer/countdown values alter prediction scores;
- require fixed recent-trade count or tick-span thresholds before the original engine may run;
- claim Binance reference settlement is BC.GAME result truth;
- expose DeTrade tokens or secrets;
- silently change strategy identity, features, thresholds, product duration, or outcome semantics;
- enable GitHub Actions if the owner has asked not to use them.

## Validation Requirements

Every prediction-core or timing change must preserve tests proving:

- bullish original-context + flow can produce UP;
- bearish original-context + flow can produce DOWN;
- neutral/conflicting evidence can produce NO_TRADE;
- strategy identity is exactly `BTC_ORIGINAL_INTELLIGENCE_TIMER_V1`;
- thresholds remain 6/3;
- changing timer metadata cannot change direction, scores, or margin;
- wrong/late/stale synchronized rounds are rejected by the timing layer, not by rewriting prediction.

## Instruction Precedence

When instructions conflict:

1. explicit current owner instruction;
2. this `AGENTS.md`;
3. `docs/PRODUCT_SPEC.md`;
4. `docs/ARCHITECTURE.md`;
5. `docs/STRATEGY_RULES.md`;
6. other repository documentation;
7. historical implementation details.
