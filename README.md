# BC.GAME TRADE

Telegram signal platform specialized for **BC.GAME BTC/USD 5-second Up/Down rounds**.

## V1 Scope

- Product: BC.GAME Up/Down
- Game market: BTC/USD
- External analysis feed: BTCUSDT initially
- Duration: 5 seconds
- Initial stake band: $1-50
- Timing mode: `MANUAL_SYNC`
- Supported countdown confirmations: `15,14,13,12`
- Outputs: `UP`, `DOWN`, `NO_TRADE`, `UNAVAILABLE`
- Manual user execution only
- Manual affiliate verification before access
- Render Web + Background Worker + PostgreSQL

## Real Round Contract

Users place UP/DOWN orders during BC.GAME's countdown. When the countdown ends BC.GAME records Start Rate at the first flag. Five seconds later it records End Rate at the second flag. End > Start means UP wins; otherwise DOWN wins according to the supplied How to Trade instructions.

The countdown is the **order window**, not the five-second measurement itself.

## Current Timing Contract

V1 is deployable in `LIVE + MANUAL_SYNC` mode without pretending that automatic BC.GAME/DeTrade round synchronization already exists.

The player prepares BC.GAME first, enters the desired stake, waits for a fresh round, then taps the Telegram button matching the visible BC.GAME countdown at **15, 14, 13, or 12 seconds**. The backend timestamps that confirmation, analyzes the already-running BTC market feed, and rejects the round if too little action time remains.

Manual timestamps are estimates based on the player's countdown confirmation. They are not represented as official BC.GAME round IDs or official Start/End Rates.

`AUTO_SYNC` remains a future upgrade boundary for a legitimate/reliable BC.GAME or DeTrade structured round source. It is not a blocker for the current manual-sync V1.

## Signal Philosophy

The engine focuses on immediate BTC microstructure: tick velocity, acceleration, aggressive buy/sell flow and micro-volatility, with slower candle indicators used only as context. It deliberately supports `NO_TRADE` and does not force a signal every round.

Binance BTCUSDT is an external analysis/reference feed. It must not be described as BC.GAME settlement truth.

## User Flow

1. `/start`
2. Registration
3. Deposit
4. BC.GAME User ID
5. Profile screenshot
6. Deposit screenshot(s)
7. Packet goes directly to bot owner's private chat
8. Owner approves/rejects/resubmits after affiliate-dashboard check
9. Approved menu opens
10. User opens BC.GAME Up/Down and prepares BTC/USD, 5s and stake
11. User selects `⚡ BTC 5s Signal`
12. Bot explains the Start Rate → 5s → End Rate target
13. User waits for a fresh BC.GAME countdown
14. User taps the matching `15s`, `14s`, `13s`, or `12s` button
15. Backend checks access, worker health, fresh market data, timing and strategy quality
16. Returns `UP`, `DOWN`, `NO_TRADE`, or `UNAVAILABLE`
17. User manually taps the indicated direction on BC.GAME before countdown zero
18. External-reference outcomes may be recorded for diagnostics; BC.GAME Start/End Rate remains the eventual product truth when reliable ingestion is integrated

## Non-goals

- no automated BC.GAME trade placement
- no Martingale/recovery logic
- no guaranteed-win claims
- no automatic copying of leaderboard traders
- no additional coins, durations or products without explicit approval

## GitHub Actions

GitHub Actions workflows are intentionally disabled at the owner's request while the monthly Actions allowance is unavailable. Repository review/editing may continue, but validation is performed through local/Render/runtime checks rather than Actions.

See `AGENTS.md` and `docs/` for the permanent contract.
