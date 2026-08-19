# Product Specification

## Product Definition

BC.GAME TRADE is an on-demand Telegram signal assistant specialized for **BTC/USD 5-second Up/Down rounds on BC.GAME**.

Observed game flow:

1. A new order countdown starts at 15 seconds.
2. Users choose UP or DOWN before the countdown ends.
3. At countdown end / first flag, BC.GAME records the **Start Rate**.
4. The selected contract runs for **5 seconds**.
5. At the second flag, BC.GAME records the **End Rate**.
6. `End Rate > Start Rate` => UP wins; otherwise DOWN wins according to the supplied How to Trade instructions.

V1 targets the visible `5s $1-50` band first. `$50-100` and `$100-200` remain out of scope until measured and approved.

## Important Data Boundary

BC.GAME displays BTC/USD. Binance BTCUSDT is the initial external analysis/reference feed because it provides fast trade/tick data, but it is **not BC.GAME settlement truth**. Until exact DeTrade/BC.GAME Start Rate and End Rate ingestion is integrated, automatically tracked outcomes remain external-reference diagnostics.

## Timing Modes

### MANUAL_SYNC — deployable V1

The player prepares BC.GAME before scanning:

1. Open BC.GAME Up/Down.
2. Select BTC/USD and 5s.
3. Enter the desired stake first.
4. Wait for a fresh countdown starting at 15 seconds.
5. In Telegram choose `⚡ BTC 5s SIGNAL`.
6. Tap the button matching BC.GAME at `15s`, `14s`, `13s`, or `12s`.
7. The backend timestamps that tap, estimates the current Start/End reference window, uses already-running market data, and returns `UP`, `DOWN`, `NO_TRADE`, or `UNAVAILABLE`.
8. If too little time remains after calculation, the bot rejects the round and tells the player to wait for the next fresh countdown.

### AUTO_SYNC — future upgrade

A verified structured DeTrade/BC.GAME round feed may later supply the real countdown, round ID, Start/End timestamps, rates, payouts and pools automatically. It should replace manual confirmation behind the existing timing adapter without changing the rest of the product.

## User States

`NEW`, onboarding states, `PENDING_REVIEW`, `APPROVED`, `REJECTED`, `RESUBMISSION_REQUIRED`, `SUSPENDED`, `BLOCKED`.

## Guided Onboarding

Before approval there is no normal menu. Flow:

1. Registration guidance using configured affiliate link.
2. Deposit guidance.
3. Text BC.GAME User ID.
4. Profile screenshot showing User ID.
5. One or more deposit screenshots.
6. Backend completeness validation.
7. Complete packet sent immediately to the bot owner's private Telegram chat.
8. Owner checks BC.GAME affiliate dashboard manually.
9. Approve / Reject / Request Resubmission.
10. Resubmission preserves old evidence history.
11. Only APPROVED users receive the normal menu.

## Approved User Main Menu

- `⚡ BTC 5s SIGNAL`
- `📈 MY RESULTS`
- `ℹ️ HOW IT WORKS`
- `🆘 SUPPORT`

Owner additionally receives admin controls.

## Signal UX Contract

1. Approved user selects `⚡ BTC 5s SIGNAL`.
2. Bot shows the preparation rule and four timer buttons: `15s`, `14s`, `13s`, `12s`.
3. User taps the button matching the visible BC.GAME timer immediately.
4. Backend checks access, signals switch, worker heartbeat, external data freshness, cached context readiness and strategy health.
5. Engine returns `UP`, `DOWN`, `NO_TRADE`, or `UNAVAILABLE`.
6. After computation, backend checks that enough estimated ordering time remains. If not, no actionable signal is returned.
7. LIVE `UP/DOWN` shows the direct BC.GAME Up/Down button and states that it applies only to the current manually confirmed round.
8. If the BC.GAME timer is already below roughly the configured minimum when the result arrives, the user must skip the round.
9. `NO_TRADE` means deliberately skip the round.
10. `UNAVAILABLE` means service/data/timing health prevented a valid decision; it is not strategy `NO_TRADE`.

PAPER deployments never issue actionable user signals. The default Blueprint is PAPER with signals and broadcasts disabled. LIVE MANUAL_SYNC is an explicit controlled-beta promotion, not a first-boot default.

## Signal Card — LIVE V1

```text
⚡ BTC/USD — BC.GAME 5s UP/DOWN

🟢 UP   or   🔴 DOWN
Quality: <calibrated label>
Contract: 5s • $1-50
Estimated Start: <time>
Estimated End: <time>

Tap the same direction on BC.GAME before its countdown reaches 0.

⏱ Manual timer sync
Use this direction only for the round whose timer you just confirmed.
If BC.GAME is already below the safe remaining-time threshold, skip the round.
```

Buttons:

- `🚀 Open BC.GAME Up/Down`
- `🔄 Next Round`
- `⬅️ Main Menu`

Do not overload the card with indicators. Backend evidence belongs in logs/research records.

## Signal Intelligence Scope

### Context features

- short trend / regime
- volatility
- support/resistance proximity
- short momentum

### Primary 5-second features

- tick price velocity at approximately 1s / 3s / 5s
- acceleration
- aggressive buy/sell trade-flow imbalance
- very-short-window volume/trade activity
- micro-volatility
- spread/liquidity and order-book imbalance when added later
- cross-exchange agreement when validated

A slow indicator by itself must never trigger a 5-second signal.

The click path must not download market history per user. Slow candle context is refreshed in the background and current ticks are maintained continuously in memory. Near-simultaneous scans may share one calculation.

## BC.GAME Round Research Fields

When a reliable structured source is discovered, collect:

- genuine round identifier
- order-window start/end timestamps
- Start Rate timestamp/value
- End Rate timestamp/value
- actual UP/DOWN result
- UP/DOWN payout percentage
- UP/DOWN pool amounts
- UP/DOWN player counts
- selected 5-second stake band

Synthetic MANUAL_SYNC IDs must not be stored as genuine BC.GAME round records. Pool/player and leaderboard data are research data, not directional evidence until validated statistically. Copy Top Trade is outside V1.

## Outcome Contract

Primary truth for product validation is BC.GAME Start Rate versus End Rate. External exchange prices may be stored as reference diagnostics but must not overwrite BC.GAME-labelled outcomes.

For MANUAL_SYNC, background outcome tracking is diagnostic and is not pushed as a second burst of Telegram messages; users can inspect stored status through My Results while exact BC.GAME result ingestion remains a future upgrade.

## Frontend Rules

- Few screens, few images, few buttons.
- No menu wall before approval.
- The signal path must be fast enough for the short countdown.
- Avoid images during the time-sensitive signal flow.
- User enters stake on BC.GAME before scanning; Telegram does not ask for the bet amount.
- Backend state is authoritative.
- BC.GAME links are configuration-driven.
- Never encourage Martingale, loss recovery, guaranteed profit, or forced round participation.

## Admin Features

- Verification decisions in owner's private bot chat
- Approved/suspended user management
- Signals on/off
- LIVE/PAPER and MANUAL_SYNC/AUTO_SYNC status
- Worker/data health
- Strategy version
- Broadcast composer and summary
- Database/retention health

## Broadcasts

Broadcasts target approved active users only, are rate-limited, record delivery summaries, and must never block the time-sensitive scan path.

Eligibility is checked again immediately before delivery so suspension/blocking takes effect for already queued work.
