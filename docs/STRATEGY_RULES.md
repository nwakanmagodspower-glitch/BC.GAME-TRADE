# Signal Intelligence Rules

## V1 Target

- Game display market: `BTC/USD`
- External analysis symbol: `BTCUSDT` initially
- BC.GAME product: `UP_DOWN`
- Duration: **5 seconds**
- Initial stake band: **$1-50**
- Execution: manual user action only
- Scan mode: on demand for the next synchronized BC.GAME round

## Actual Outcome Definition

The supplied BC.GAME How to Trade instructions define the round as:

1. User places UP/DOWN order during countdown.
2. When countdown ends, BC.GAME records Start Rate at first flag.
3. Five seconds later, BC.GAME records End Rate at second flag.
4. End Rate > Start Rate => UP wins.
5. Otherwise DOWN wins according to the supplied rules.

The countdown itself is not the five-second prediction horizon.

## Decision Space

`UP | DOWN | NO_TRADE | UNAVAILABLE`

`NO_TRADE` is expected and important. The system must not force participation in every round.

## Primary Five-Second Features

Current implementable inputs:

- 1-second tick return
- 3-second tick return
- 5-second tick return
- tick acceleration
- aggressive buy/sell trade-flow ratio
- number of recent trades
- 5-second micro-volatility

Context only:

- short EMA relationship
- 1-minute market structure
- RSI
- 1-minute volume/taker context
- broader volatility/support-resistance context

A slow/candle indicator alone cannot create a five-second signal.

## Planned Microstructure Extensions

Add only after reliable implementation and measurement:

- best bid/ask spread
- top-of-book imbalance
- multi-level order-book imbalance
- microprice
- book replenishment/cancellation pressure
- cross-exchange short-horizon divergence
- liquidation/open-interest context if shown to improve the specific five-second objective

## BC.GAME-Specific Research Inputs

Collect when a reliable structured source is discovered:

- round ID and countdown
- first-flag Start Rate
- second-flag End Rate
- UP/DOWN payout percentages
- pool amounts
- player counts
- stake band

Do not assume crowd/pool direction predicts price. Test it first.

Leaderboard/Copy Top Trade is excluded from V1 direction logic.

## Round Synchronization

LIVE direction delivery requires either a valid fresh `MANUAL_SYNC` countdown confirmation (15/14/13/12) or, in the future, a trustworthy fresh `AUTO_SYNC` round snapshot. Never use minute boundaries or an unconfirmed local timer.

A signal must leave enough order-window lead time for a human to receive the Telegram message, open/return to BC.GAME, set amount and press UP/DOWN before countdown reaches zero.

If the remaining window is too short, skip the round.

## Strategy Principles

- Optimize specifically for direction between BC.GAME Start Rate and End Rate five seconds later.
- Treat Binance BTCUSDT as analysis/reference data, not settlement truth.
- Use microstructure first; use slow indicators as regime/context filters.
- Do not copy a Forex/futures strategy.
- Do not use Martingale/recovery logic.
- Do not fabricate confidence percentages.
- Calibrate confidence only from forward/backtested five-second labels that match the real game semantics.
- Prefer fewer high-quality signals over frequent weak signals.

## Direction vs Expected Value

Keep two questions separate:

1. **Direction:** is UP or DOWN sufficiently more likely over the five-second target?
2. **Economics:** is the current displayed payout sufficient for the measured probability?

Do not let payout change the predicted direction. Payout may veto a direction as `NO_TRADE` once reliable payout data is available.

## Result Truth

For product validation, BC.GAME Start Rate / End Rate is the desired ground-truth label.

External reference settlement is allowed only for PAPER diagnostics and must be labelled as such. A close external-feed result must not be represented as proof of a BC.GAME win/loss.

If reliable BC.GAME end-rate data is missing, result is unresolved rather than guessed.

## Strategy Versioning

Use immutable identities such as:

```text
BTC_UPDOWN_5S_V1.1_DEPTH
BTC_UPDOWN_5S_V2.0_CALIBRATED
```

Material changes to thresholds, features, duration, round timing or outcome logic require a new version.

## Evaluation

Track at minimum:

- scans
- directional signals
- NO_TRADE rate
- UNAVAILABLE rate
- late/too-short-window skips
- cancellations before Start Rate
- resolved/unresolved outcomes
- wins/losses by BC.GAME labels when available
- external-vs-BC.GAME price disagreements
- performance by direction
- performance by micro-volatility regime
- performance by time of day
- performance by payout band
- performance by strategy version

## Historical Research

The old one-minute / five-minute backtest is no longer a valid validator for this product contract. One-minute candles may remain useful for context research, but five-second model evaluation requires sufficiently fine-grained trade/tick/order-book history.

No-lookahead rules still apply: every feature must use only data available before the predicted BC.GAME Start Rate.

## Forward PAPER Validation

This becomes the most important validation phase:

1. observe synchronized BC.GAME rounds;
2. capture pre-Start-Rate features;
3. record model decision without encouraging a real trade;
4. capture BC.GAME Start Rate and End Rate;
5. label actual round result;
6. compare with external reference behavior;
7. collect enough rounds across regimes before considering LIVE.

A strong-looking small sample is not enough evidence of a durable edge.
