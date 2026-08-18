# AGENTS.md

These rules govern every coding agent, developer, automation, and deployment change in this repository.

## Product Boundary

V1 is intentionally narrow and is based on the observed BC.GAME Up/Down interface and supplied How to Trade flow:

- BC.GAME product: **Up/Down**
- Game display market: **BTC/USD**
- External analysis market: **BTCUSDT initially**, treated only as a reference/analysis feed until BC.GAME price-source matching is validated
- Contract duration: **5 seconds**
- Initial stake band: **5s $1-50**; other stake bands are research-only until explicitly approved
- User action: **on-demand scan for the current fresh BC.GAME round**
- Outputs: `UP`, `DOWN`, `NO_TRADE`, `UNAVAILABLE`
- Manual user execution on BC.GAME only
- Manual affiliate verification before access

The observed BC.GAME game contract is round-based: users place orders during a countdown that starts at 15 seconds; when the countdown ends BC.GAME records the Start Rate at the first flag; after the selected 5-second period BC.GAME records the End Rate at the second flag. End > Start means UP wins; otherwise DOWN wins according to the supplied game instructions.

### V1 timing mode — MANUAL_SYNC

Automatic DeTrade/BC.GAME round data is not required for the first deployable V1. The user must prepare BC.GAME first, enter the stake, wait for a fresh countdown, then tap the Telegram button matching the visible timer at **15, 14, 13, or 12 seconds**. The backend timestamps that confirmation, estimates the current Start/End reference windows, computes the signal from already-running market data, and rejects the result if too little human-action time remains.

### Future upgrade — AUTO_SYNC

A verified structured DeTrade/BC.GAME feed may later replace the manual timer confirmation. It must plug into the existing round adapter and must not require a redesign of onboarding, signal intelligence, persistence, or Telegram menus.

Do not expand scope unless an explicit milestone authorizes it.

## Mandatory Rules

Every implementation MUST:

- preserve BTC/USD 5-second BC.GAME Up/Down as V1 product scope;
- treat BTCUSDT/Binance as an analysis feed, not BC.GAME settlement truth;
- keep Telegram separate from signal intelligence;
- keep market-data providers replaceable;
- keep BC.GAME-specific round/product logic behind an adapter;
- version every production strategy;
- record generated directional/no-trade decisions and diagnostic outcomes when a usable reference exists;
- label manual Start/End timestamps as estimated rather than BC.GAME-issued facts;
- allow LIVE manual execution in `MANUAL_SYNC` only when the user explicitly confirms 15/14/13/12 seconds and enough action time remains;
- require verified structured round synchronization before `AUTO_SYNC` is enabled;
- fail closed when external market data, worker health, or required timing input is stale/unhealthy;
- preserve `NO_TRADE` as a first-class outcome;
- keep secrets out of GitHub;
- use database migrations for schema changes;
- keep Render compatibility;
- preserve PAPER/LIVE separation and owner kill switches;
- keep onboarding state persistent;
- keep Telegram UI minimal while backend validation and audit trails remain complete;
- keep latency visible: a signal that cannot reach a human with enough time to act before BC.GAME order close is not actionable;
- keep the scan path cache-first and avoid per-user market-data downloads.

## Prohibited Changes

Do NOT:

- add coins, durations, or BC.GAME products without approval;
- implement automatic BC.GAME trade placement in V1;
- add Martingale, loss chasing, or forced recovery logic;
- fabricate confidence scores;
- claim guaranteed accuracy or guaranteed profit;
- treat leaderboard win rates, Copy Top Trade, or crowd/pool direction as predictive without measured evidence;
- treat Binance settlement as identical to BC.GAME settlement without validation;
- represent a synthetic MANUAL_SYNC identifier as a genuine BC.GAME round ID;
- bypass manual access approval;
- expose the main menu before onboarding/approval is complete;
- hardcode admin IDs throughout business logic;
- silently change thresholds, feature weights, duration rules, or timing rules;
- overwrite historical strategy results after a new version is deployed;
- allow stale market data or insufficient action time to produce an actionable signal;
- allow broadcasts to block signal requests;
- store unnecessary raw market streams indefinitely in PostgreSQL;
- re-enable GitHub Actions while the owner has asked that Actions not be used.

## Verification Funnel Contract

Before approval, the bot is a guided workflow, not a menu-driven bot:

1. Registration guidance.
2. Deposit guidance.
3. BC.GAME User ID.
4. Profile screenshot.
5. Deposit screenshot(s).
6. Validate completeness.
7. Forward the complete packet directly to the bot owner's private Telegram chat.
8. Persist pending review.
9. Owner checks affiliate dashboard manually.
10. Owner chooses approve, reject, or request resubmission.
11. Only `APPROVED` users receive the normal bot menu.

Resubmission must preserve the previous reviewed packet as history.

## Signal Safety Contract

An actionable MANUAL_SYNC directional signal may be returned only when:

- approved user access is valid;
- signals are enabled;
- dedicated worker health is fresh;
- external BTC market data is fresh;
- the cached slow-context data is ready;
- the configured strategy is active;
- the product/duration/stake band match supported V1 scope;
- the user selected one of the permitted visible countdown values: 15, 14, 13, or 12;
- enough human-action time remains after calculation;
- quality thresholds are met.

Otherwise return `NO_TRADE` or `UNAVAILABLE` and tell the user to skip the round when appropriate.

In MANUAL_SYNC, once the actionable direction has been delivered, background reference tracking must not later reverse or cancel what the user already received. External start/end outcomes are diagnostic until exact BC.GAME Start Rate / End Rate ingestion is verified.

## Source of Truth

When instructions conflict, use this precedence:

1. Explicit current owner instruction.
2. `AGENTS.md`.
3. `docs/PRODUCT_SPEC.md`.
4. `docs/ARCHITECTURE.md`.
5. `docs/STRATEGY_RULES.md`.
6. Other repository documentation.
7. Existing implementation details.
