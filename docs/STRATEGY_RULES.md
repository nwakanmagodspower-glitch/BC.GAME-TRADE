# Signal Intelligence Rules

## V1 Research Target

- Pair: `BTCUSDT`
- BC.GAME product: `UP_DOWN`
- Execution: user/manual
- Scan mode: on demand
- Expiry: configurable; 300 seconds is the initial research default, not a permanent hard-coded truth.

## Decision Space

The engine returns exactly one of:

- `UP`
- `DOWN`
- `NO_TRADE`
- `UNAVAILABLE`

`NO_TRADE` is a valid and expected result.

## V1 Feature Families

- short-term trend
- momentum
- market structure
- volume
- volatility
- support/resistance context

Possible later additions after measurement:

- order-flow imbalance
- order-book imbalance
- liquidations
- open interest
- cross-exchange divergence
- BC.GAME pool/payout/reference-price inputs

## Strategy Principles

- Do not treat a single indicator as a trade command.
- Do not copy a Forex/futures strategy without validating it against the fixed-expiry Up/Down objective.
- Optimize for short-horizon BTC direction at the configured settlement horizon.
- Market-regime detection precedes directional scoring.
- Confidence must be calibrated from observed/backtested performance; never fabricate percentages from arbitrary indicator counts.
- Payout/expected-value gating may be added once reliable BC.GAME payout data is available.

## Timing

Every directional candidate must contain:

- signal creation time
- planned entry time
- entry validity window
- expiry time

A candidate must be revalidated before planned entry. If invalidation conditions trigger, mark `CANCELLED`; do not instruct entry.

## Data Health

Signal generation requires fresh market data. Freshness thresholds are configuration, not magic constants scattered in code.

If provider health, timestamps, or snapshot integrity fail, return `UNAVAILABLE` rather than guessing.

## Strategy Versioning

Use immutable names such as:

```text
BTC_UPDOWN_V1.0
BTC_UPDOWN_V1.1
BTC_UPDOWN_V2.0_ORDERFLOW
```

Changing weights, thresholds, feature logic, expiry behavior, or timing logic requires a new strategy version when the change can materially affect outcomes.

## Evaluation

Track at minimum:

- generated directional signals
- no-trade rate
- cancellations
- wins/losses/ties/unresolved
- performance by market regime
- performance by time-of-day
- performance by strategy version
- data-provider health at decision time

Backtests must match the actual entry/expiry semantics as closely as possible. Live paper forward-testing is required before production signal mode.