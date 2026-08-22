# BCGAME Trading Reference

This document separates facts observed from the live BC.GAME Up/Down product / supplied How to Trade text from assumptions. Future agents must not convert unknowns into hard-coded behavior.

## Verified From The Supplied Live Up/Down Interface

Target page: `https://bc.game/trading/up-down`

Observed product identity:

- displayed pair: **BTC/USD**;
- contract duration shown: **5s**;
- visible stake bands include `5s $1-50`, `5s $50-100`, and `5s $100-200`;
- V1 intentionally targets `$1-50` first;
- user enters an amount and manually chooses `UP` or `DOWN`;
- order controls are enabled during the countdown and disabled while the round settles/transitions;
- interface shows live price/chart, recent UP/DOWN outcomes, pool/player information, Positions, History, Leaderboard, and Copy Top Trade;
- interface shows dynamic UP/DOWN payout/return percentages that can differ between sides and rounds;
- live chart shows a Detrade mark; the exact underlying settlement/reference feed still requires technical confirmation.

## Verified From Supplied How to Trade Text

The supplied page instructions state:

1. Choose upward or downward direction within the specified countdown time.
2. The interface shows total order amount in UP and DOWN pools and user/order status.
3. When countdown ends, the system enters settlement preparation and records the **starting price at the first flag**.
4. After the K-line runs for the selected period, the system records the **ending price at the second flag**.
5. Compare End Rate with Start Rate.
6. If End Rate is greater than Start Rate, UP wins.
7. Otherwise DOWN wins according to the supplied instructions.
8. The system then displays winning/losing pool results and the user's profit when applicable.

This means the visible countdown is an **order window**. The selected 5 seconds is the **measurement period after Start Rate is recorded**.

## Verified From Supplied Result Screens

The live page exposes exact result values in a Start Rate / End Rate panel. Supplied examples include both outcomes:

```text
Start 64565.15683
End   64564.7861
=> DOWN
```

```text
Start 64565.80479
End   64566.03266
=> UP
```

This confirms that BC.GAME's displayed Start/End Rate is the target product label our model should ultimately be evaluated against.

## Separate Leveraged Futures Product

BC.GAME also has conventional leveraged futures. That product is not this repository's V1 target. Do not add leverage, stop loss, take profit, liquidation or position-management logic to the Up/Down signal engine.

## V1 Product Interpretation

The prediction objective is:

```text
Using only information available before BC.GAME records Start Rate,
estimate whether BC.GAME End Rate approximately 5 seconds later
will be above or below BC.GAME Start Rate.
```

The external analysis provider may use BTCUSDT, but the product display/label is BTC/USD and BC.GAME Start/End Rate remains outcome truth.

## Dynamic Payout / Pool Facts

The interface visibly exposes:

- UP payout/return;
- DOWN payout/return;
- UP pool amount;
- DOWN pool amount;
- number of players on each side.

Engineering rule: store these when a reliable structured source is integrated, but do not assume they predict direction. Direction and expected-value/payout filtering remain separate research questions.

## Leaderboard / Copy Top Trade

The interface exposes trader `Winning/Order`, win rate, PnL and profit plus a Copy Top Trade feature.

Engineering rule: leaderboard/copy-trade data is **not V1 signal evidence**. Historical leaderboard percentages can be selection-biased and do not establish a repeatable predictive edge.

## Verified Authenticated Timer Discovery

The later browser/CDP investigation confirmed the DeTrade WebSocket route, authenticated subscription, round identifier, round status/timestamps, zlib encoding, and `priceStartTime` countdown boundary. See `DETRADE_AUTH_TIMER.md` for the redacted protocol record.

## Still Unconfirmed

Must remain research/integration questions:

- exact Detrade/BC.GAME price source/index composition;
- timestamp precision and network latency for Start Rate/End Rate;
- tie/equality handling beyond the supplied wording that otherwise assigns DOWN;
- whether stake bands differ only economically or also by pool/round behavior;
- exact payout formula, fees/house allocation and pool mathematics;
- documented stability/support guarantees for the observed internal protocol;
- exact ephemeral token lifetime and an official unattended refresh grant;
- regional/account differences.

## Engineering Consequences

- Duration is locked to 5s for V1.
- The old 300-second/minute-boundary architecture is retired.
- `BCGameRoundService` owns round synchronization.
- `HYBRID_SYNC` uses verified DeTrade timing when authorized and the single Scan Now fallback only when that source is unavailable.
- A known unsafe authoritative frame never falls through to manual timing.
- Binance BTCUSDT is analysis/reference only.
- External-reference outcomes remain PAPER diagnostics until BC.GAME Start/End Rate ingestion is integrated.
- Unknown internal endpoints must not be relied on silently; use health checks and fail closed.

## Rule for Future Agents

When uncertain, preserve the uncertainty. Do not turn an observed UI pattern or undocumented network call into a permanent BC.GAME fact without measurement and documentation.
