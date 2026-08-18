# BC.GAME TRADE

Telegram signal platform specialized for **BC.GAME BTC/USD 5-second Up/Down rounds**.

## V1 Scope

- Product: BC.GAME Up/Down
- Game market: BTC/USD
- External analysis feed: BTCUSDT initially
- Duration: 5 seconds
- Initial stake band: $1-50
- On-demand `Scan Next Round`
- Outputs: `UP`, `DOWN`, `NO_TRADE`, `UNAVAILABLE`
- Manual user execution only
- Manual affiliate verification before access
- Render Web + Background Worker + PostgreSQL

## Real Round Contract

Users place UP/DOWN orders during BC.GAME's countdown. When the countdown ends BC.GAME records Start Rate at the first flag. Five seconds later it records End Rate at the second flag. End > Start means UP wins; otherwise DOWN wins according to the supplied How to Trade instructions.

The countdown is the **order window**, not the five-second measurement itself.

## Signal Philosophy

The engine focuses on immediate BTC microstructure: tick velocity, acceleration, aggressive buy/sell flow and micro-volatility, with slower candle indicators used only as context. It deliberately supports `NO_TRADE` and does not force a signal every round.

LIVE actionable delivery requires trustworthy BC.GAME round synchronization. Until that integration exists, the product remains PAPER/research and must not invent round timing from minute boundaries.

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
10. User selects `⚡ BTC 5s Signal`
11. Bot explains the Start Rate → 5s → End Rate target
12. User taps `🔍 Scan Next Round`
13. Backend checks access, worker, market data, round timing and strategy quality
14. Returns UP/DOWN/NO_TRADE/UNAVAILABLE
15. Outcomes are measured against BC.GAME Start/End Rate when reliable round-result ingestion is available

## Non-goals

- no automated BC.GAME trade placement
- no Martingale/recovery logic
- no guaranteed-win claims
- no automatic copying of leaderboard traders
- no additional coins, durations or products without explicit approval

## GitHub Actions

GitHub Actions workflows are intentionally disabled at the owner's request while the monthly Actions allowance is unavailable. Repository review/editing may continue, but validation is performed through local/Render/runtime checks rather than Actions.

See `AGENTS.md` and `docs/` for the permanent contract.
