# Signal Intelligence Rules

## V1 Research Target

- Pair: `BTCUSDT`
- BC.GAME product: `UP_DOWN`
- Execution: user/manual
- Scan mode: on demand
- Production V1 expiry: **300 seconds**.

The broader research framework may evaluate other horizons deliberately, but the deployed `BTC_UPDOWN_V1.x` contract remains locked to 300 seconds. A materially different production expiry requires explicit approval, validation, and a versioned strategy change rather than silently changing configuration.

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

Every directional candidate must contain signal creation time, planned entry time, entry validity window, and expiry time.

A candidate must not activate before its exact planned entry timestamp. At or after planned entry and before the entry window closes, rerun V1 intelligence. If data is unavailable, the setup becomes `NO_TRADE`, or direction changes, cancel the candidate rather than activating stale analysis.

For forward PAPER/LIVE reference settlement, accept only a fresh market event at or after the intended expiry timestamp and within the configured small settlement window. If that reference cannot be captured reliably, mark the signal unresolved/`EXPIRED`; do not assign WIN/LOSS/TIE from a materially late price.

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

Changing weights, thresholds, feature logic, production expiry behavior, or timing logic requires a new strategy version when the change can materially affect outcomes.

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

Backtest reports should include at least overall win/loss/tie counts, signal coverage/no-trade rate, and breakdowns by direction, quality, market structure, and entry hour.

## Walk-Forward Validation Contract

Parameter research must not select and judge parameters on the same historical period.

The walk-forward engine therefore:

- divides history into chronological training and validation windows;
- evaluates candidate `min_score` / `min_margin` combinations on the training window only;
- requires a minimum number of training signals before a candidate can be selected;
- selects the training candidate using declared ranking rules;
- applies the selected parameters unchanged to the immediately following unseen validation window;
- advances chronologically and repeats the process across multiple folds;
- reports aggregate validation performance separately from training performance.

Default research windows are 14 training days followed by 7 unseen validation days. These are research defaults and may be changed deliberately, but they must not be tuned repeatedly just to improve one historical report.

A parameter set should be considered more credible when validation performance remains reasonably stable across multiple market periods, directions, and signal counts. One exceptionally strong fold is not sufficient evidence of a durable edge.
