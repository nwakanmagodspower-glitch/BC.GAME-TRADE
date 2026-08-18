# BC.GAME Trading Reference

This document separates verified product facts from assumptions. Future agents must not convert unconfirmed details into hard-coded behavior.

## Verified From BC.GAME Sources

### Up/Down / High Low

BC.GAME describes Up/Down / High Low as a short-duration directional product: the user predicts whether price will be higher or lower than the starting price when the selected countdown/timeframe ends. BC.GAME examples mention short windows such as 1 minute and 5 minutes.

Reference:
- https://blog.bc.game/a-complete-guide-to-bc-games-crypto-futures-trading/
- https://blog.bc.game/long-vs-short-explaining-the-simple-up-or-down-bet/

### Separate Leveraged Futures Product

BC.GAME also documents a conventional leveraged futures product with trading pairs such as BTC/USDT and ETH/USDT, leverage, Up/Down positions, stop-loss, take-profit, manual closing, funding for sufficiently long-held positions, and a single trading price.

This is **not** the V1 product targeted by this repository.

Reference:
- https://help.bc.game/en/articles/10722034-future-trading-how-it-works

### Trading/Futures Reward Treatment

BC.GAME Help Center states that wagers in Trading/Futures do not currently contribute to XP/wager-based bonus unlocking in the same way as traditional game wagers.

Reference:
- https://help.bc.game/en/articles/7831369-deposit-bonus-and-locked-bcd-rakeback-all-your-questions-answered

## V1 Product Interpretation

For this repository, `BC_UPDOWN` means the short-duration directional contract described above, not the separate leveraged futures position product.

The intelligence objective is therefore approximately:

```text
Given BTC reference price at planned entry T,
estimate whether the settlement/reference price at T + expiry
will be above or below entry.
```

## Still Unconfirmed / Must Remain Configurable

The following must not be treated as verified until observed from the live product or confirmed by authoritative documentation:

- complete current Up/Down pair list;
- exact BTC/USDT expiry choices available to the target account/region;
- exact live payout/pool formula and how it varies;
- exact settlement/tie behavior;
- exact reference-price provider/index used by BC.GAME Up/Down;
- exact timestamp rounding/latency behavior at entry and settlement;
- current minimum/maximum stake limits;
- stable public BC.GAME Trading/Up-Down API availability;
- stability of any undocumented/internal BC.GAME endpoint discovered later.

## Engineering Consequence

These unknowns are **adapter/configuration concerns**, not reasons to rewrite the architecture.

- Expiry remains configurable.
- Market provider remains replaceable.
- BC.GAME-specific reference/payout/pool data goes through `BCGameAdapter`.
- Any undocumented endpoint must have health checks and graceful degradation.
- V1 signal intelligence can be researched using independent BTC market data while BC.GAME-specific settlement matching is measured separately.

## Rule for Future Agents

If a value is not listed under Verified From BC.GAME Sources or confirmed by a newer authoritative source/live measurement, do not hard-code it as a BC.GAME fact. Add it as configuration, an experiment, or a documented assumption.