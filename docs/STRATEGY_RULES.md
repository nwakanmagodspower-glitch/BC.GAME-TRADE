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

## Historical Backtest Contract

The M6 candle backtest follows strict no-lookahead rules:

- Features are calculated only from closed 1-minute candles available at decision time.
- Entry uses the next 1-minute candle open, approximating the next synchronized minute boundary.
- A 5-minute expiry uses the open price exactly five one-minute intervals after entry.
- Future candles are used only for labeling the already-created historical signal, never for feature calculation.
- Historical trade-flow/order-book inputs are not fabricated when tick-level history is unavailable.

The initial historical source is external `BTCUSDT` market data. A backtest result therefore measures the strategy against that external reference feed; it is **not** proof that BC.GAME would have settled every contract identically.

Before production claims are made, compare external entry/expiry prices with BC.GAME's actual live Up/Down reference/settlement behavior and complete live paper forward-testing.

Backtest reports should include at least overall win/loss/tie counts, signal coverage/no-trade rate, and breakdowns by direction, quality, market structure, and entry hour. Parameter changes selected after looking at test results must be validated on unseen time periods rather than repeatedly optimized on the same sample.
