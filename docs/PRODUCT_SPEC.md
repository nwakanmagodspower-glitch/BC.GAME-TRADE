# Product Specification

## Scope

- BCGAME Up/Down
- BTC/USD display market
- five-second Start Rate to End Rate contract
- `$1–$50` band
- external Binance Spot BTCUSDT analysis feed
- manual user execution only

The active prediction engine is `BTC_ORIGINAL_INTELLIGENCE_TIMER_V1`. It restores the original pre-timer intelligence. BC.GAME/DeTrade integration supplies round timing only and must not alter prediction direction or score.

## Approved-User Journey

1. Open BCGAME Up/Down and select BTC/USD, 5 Seconds, and `$1–$50`.
2. Enter the intended amount on BCGAME without tapping UP or DOWN.
3. At a fresh order window, tap `⚡ BTC 5s Signal` in Telegram.
4. The backend rechecks approval/block state and the owner signal switch.
5. HYBRID timing uses a safe synchronized DeTrade round when available; otherwise it may use manual Scan Now fallback only when the authoritative timing source itself is unavailable.
6. The original BTC intelligence runs independently of countdown values.
7. If synchronized, remaining order-window time is checked again after analysis.
8. Telegram returns UP, DOWN, NO TRADE, or UNAVAILABLE.
9. For a timely LIVE direction, the user manually returns to BCGAME and acts. If delayed, the user skips the round.

The old countdown selector, My Result, Win/Loss calibration, cross-venue prediction, and V2 engine are not active product features.

## Prediction Rules

The restored engine uses:

- EMA 9 vs EMA 21
- five-minute momentum from closed 1-minute candles
- six-candle short-term structure
- volume expansion and taker direction
- recent aggressive trade-flow ratio when available
- RSI 14
- ATR 14 quality adjustment

Qualification is fixed at minimum score 6 and minimum margin 3. Trade-flow sample count is optional evidence, not a hard availability gate.

## Signal Timing Rules

- `priceStartTime` is the betting deadline / Start Rate boundary.
- `priceEndTime - priceStartTime` must be approximately 5000 ms.
- synchronized status must be exactly `1001`.
- the frame must be fresh.
- the initial production safety margin requires more than the configured DeTrade margin before analysis.
- the post-analysis dispatch margin must still be satisfied.
- unknown, late, transition, cancelled, payout, finished, stale, and wrong-duration states are rejected.

Timing rejection does not recalculate or reverse the BTC prediction.

## Onboarding and Verification

1. Registration link and `$10+` deposit guidance.
2. BCGAME User ID.
3. Profile screenshot.
4. One to three deposit screenshots.
5. A durable background worker sends the verification packet to the owner.
6. The owner checks affiliate attribution and `$10+` deposit independently, then approves, rejects, or requests resubmission.
7. Review decisions are persisted and idempotent; temporary evidence is cleaned according to repository retention rules.

The configured owner identity retains private-chat-only admin controls.

## Non-Goals

- automatic trade execution
- storing BCGAME passwords, cookies, access codes, or browser sessions
- treating Binance settlement as BCGAME truth
- extra coins, durations, ranges, or futures products
- Martingale or loss-recovery logic
- guarantees or fabricated confidence
- timer-dependent prediction scoring
