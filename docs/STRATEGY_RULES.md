# Signal Intelligence Rules

## Active Strategy

Strategy identity: `BTC_ORIGINAL_INTELLIGENCE_TIMER_V1`

Product scope:

- BCGAME Up/Down
- game market `BTC/USD`
- external analysis symbol `BTCUSDT`
- five-second Start Rate to End Rate contract
- `$1–$50` stake band
- manual user execution only

## Direction Engine

The active engine is the original pre-timer intelligence. It is intentionally simple and must remain separate from BC.GAME timing.

### Directional evidence

1. **EMA trend**
   - EMA 9 above EMA 21: +2 bull
   - EMA 9 below EMA 21: +2 bear

2. **Five-minute momentum**
   - >= +0.08%: +2 bull
   - <= -0.08%: +2 bear

3. **Short-term structure**
   - bullish higher-high/higher-low structure: +2 bull
   - bearish lower-high/lower-low structure: +2 bear

4. **Volume + taker behavior**
   - volume ratio >= 1.20 and taker-buy ratio >= 0.55: +1 bull
   - volume ratio >= 1.20 and taker-buy ratio <= 0.45: +1 bear

5. **Recent aggressive trade flow**
   - when at least 10 classified recent trades are available:
   - buy ratio >= 0.58: +2 bull
   - buy ratio <= 0.42: +2 bear

6. **RSI 14**
   - 52–72: +1 bull
   - 28–48: +1 bear
   - >78 reduces bull by 1
   - <22 reduces bear by 1

7. **ATR 14 quality adjustment**
   - ATR% < 0.03 reduces both sides by 1
   - ATR% > 1.25 reduces both sides by 2

### Decision policy

- minimum winning score: **6**
- minimum margin over opposite side: **3**
- `STRONG`: winning score >= 8 and margin >= 4
- otherwise qualifying direction is `VALID`
- if neither side qualifies: `NO_TRADE`

These thresholds are part of the strategy identity. They must not be silently overridden by Render environment values.

## Important: Trade Flow Is Optional Evidence

Recent trade flow can strengthen a direction, but it is not a hard readiness gate. The engine may still make a decision from EMA, momentum, structure, volume/taker context, RSI, and ATR when fewer than a fixed number of recent ticks are available.

Do not restore hard requirements such as `SIGNAL_MIN_RECENT_TRADES` or `SIGNAL_MIN_TICK_SPAN_SECONDS` to the active prediction path.

## Timer Separation

BC.GAME timing does not predict direction.

The timer may:

- identify a genuine BTC/USD five-second round;
- verify status `1001`;
- verify the frame is fresh;
- verify `priceEndTime - priceStartTime` is approximately 5 seconds;
- determine how much order-window time remains;
- block delivery when there is too little time to act.

The timer may not:

- add/subtract bull or bear points;
- change EMA/momentum/structure/flow weights;
- change 6/3 qualification rules;
- make horizon-dependent score adjustments;
- flip UP to DOWN or DOWN to UP;
- force a second prediction because only the countdown changed.

A timer-invalid or late round is a **delivery/timing rejection**, not a different market prediction.

## Removed Experimental Logic

The following are not part of the active strategy:

- 1-second tick-return score
- 3-second tick-return score
- 5-second tick-return score
- tick acceleration scoring
- five-second micro-volatility scoring
- cross-venue Binance/Bybit prediction voting
- horizon-aware scoring
- unified V2 engine
- owner calibration engine
- 8/4 qualification thresholds

Historical commits may contain these experiments. They must not be reintroduced into the active engine without a new explicit research version and owner approval.

## Outcome Truth

BC.GAME Start Rate and End Rate define the real product result:

- End Rate > Start Rate → UP wins
- otherwise → DOWN wins according to the supplied product rules

Binance BTCUSDT is external analysis/reference data and must never be represented as BC.GAME settlement truth.

## Evaluation

Track separately:

- scans
- UP signals
- DOWN signals
- NO_TRADE rate
- UNAVAILABLE rate
- late/timer-rejected rounds
- synchronized vs manual-fallback delivery
- BC.GAME-resolved wins/losses when real Start/End Rate is available
- unresolved rounds
- strategy version

Do not judge the restored strategy by a handful of trades. Forward validation must preserve the exact feature definitions, 6/3 policy, and five-second BC.GAME outcome semantics.
