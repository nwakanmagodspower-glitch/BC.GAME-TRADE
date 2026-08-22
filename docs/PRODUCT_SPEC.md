# Product Specification

## Scope

- BCGAME Up/Down
- BTC/USD display market
- five-second Start Rate to End Rate contract
- `$1–$50` band
- external BTCUSDT analysis feed
- manual user execution only

The prediction engine is unchanged. This integration supplies the authoritative order-window clock and round identity when DeTrade authorization is available.

## Approved-user journey

1. Open BCGAME Up/Down and select BTC/USD, 5 Seconds, and `$1–$50`.
2. Enter the intended amount on BCGAME without tapping UP or DOWN.
3. At a fresh order window, tap `⚡ BTC 5s Signal` in Telegram.
4. The backend rechecks approval, block state, kill switch, worker health, round timing, and market freshness.
5. If synchronized timing is safe, the existing engine runs and the timer is checked again.
6. Telegram returns a compact UP, DOWN, NO TRADE, or UNAVAILABLE response.
7. For a timely LIVE direction, the user manually returns to BCGAME and acts. If delayed, the user skips the round.

The old countdown selector, My Result, and Win/Loss calibration buttons are removed. HYBRID manual fallback means the same Scan Now tap may still run when the authenticated timer source itself is unavailable; it does not fabricate a round ID or official time.

## Signal timing rules

- `priceStartTime` is the betting deadline.
- `priceEndTime - priceStartTime` must equal the verified 5000 ms contract.
- status must be exactly `1001`.
- the frame must be younger than the configured stale threshold.
- the initial default requires more than 10,000 ms remaining.
- the post-analysis default requires more than 8,000 ms remaining.
- all unknown, late, transition, cancelled, payout, and finished states are rejected.

Synchronized messages may show direction, quality, BCGAME round ID, approximate remaining time, and `Timing: synchronized`. They must stay compact and never expose authorization.

## Onboarding and verification

1. Registration link and `$10+` deposit guidance.
2. BCGAME User ID.
3. Profile screenshot.
4. One to three deposit screenshots.
5. A durable background worker sends the images together as a media group where Telegram permits, followed by one review block.
6. The owner checks affiliate attribution and `$10+` deposit independently, then approves, rejects, or requests resubmission.
7. The decision is idempotent; evidence IDs and BCGAME account ID are purged immediately.

The configured owner identity is automatically approved and retains private-chat-only admin controls.

## Non-goals

- automatic trade execution
- storing BCGAME passwords, cookies, access codes, or browser sessions
- treating external exchange settlement as BCGAME truth
- extra coins, durations, ranges, or futures products
- guarantees or fabricated confidence
