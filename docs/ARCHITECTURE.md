# Architecture

## Runtime Topology

```text
Telegram
  -> Render web: secret-validated FastAPI webhook
       -> access/onboarding/admin handlers
       -> UserSignalService
       -> BCGameRoundService / DeTradeObserver (timing only)
       -> Binance BTCUSDT market cache
       -> SignalIntelligenceService (direction only)
       -> PostgreSQL

Render worker
  -> Binance market cache
  -> advisory-lock background coordinator
       -> signal lifecycle
       -> broadcast delivery
       -> verification-packet delivery
       -> retention cleanup
       -> PostgreSQL
```

## Two Independent Decisions

The system deliberately separates prediction and timing.

### 1. Prediction

`SignalIntelligenceService` answers only:

- UP
- DOWN
- NO_TRADE
- UNAVAILABLE when required market/candle data cannot be prepared

The active prediction engine is `BTC_ORIGINAL_INTELLIGENCE_TIMER_V1` and uses the restored pre-timer feature set: EMA trend, five-minute momentum, short-term structure, volume/taker behavior, optional recent aggressive trade flow, RSI, and ATR.

The qualification policy is fixed at score 6 / margin 3.

### 2. Timing

`BCGameRoundService` and `DeTradeObserver` answer only whether the current BC.GAME order window is safe to use.

Timing metadata is attached to an already-computed intelligence result. It cannot change direction, scores, margin, feature weights, or qualification thresholds.

## Timer Decision Path

1. The observer uses a configured ephemeral DeTrade token when available.
2. It connects to `wss://websocket.detrade.com/ws`.
3. It subscribes to `/contest/BTC/USD/5/ticker/subscribe`.
4. A synchronized round is actionable only when the frame is fresh, complete, status is `1001`, and the Start→End interval is approximately 5000 ms.
5. `priceStartTime` is the authoritative order-close / Start Rate boundary.
6. The initial safety margin must be satisfied before analysis.
7. The restored prediction engine runs independently of the countdown value.
8. Remaining time is checked again after analysis against the dispatch margin.
9. If too little time remains, delivery is rejected without rewriting the prediction.

Known closed, late, stale, unknown, transition, cancelled, payout, or wrong-duration frames are synchronized-but-not-actionable and cannot fall through to manual behavior. In HYBRID mode, fallback occurs only when the authoritative timing source itself is unavailable.

## Safe Defaults vs Production

Local/default configuration:

- PAPER
- signals disabled
- broadcasts disabled
- `MANUAL_SYNC`
- DeTrade disabled

Render production explicitly overrides timing to `HYBRID_SYNC`, enables synchronized round support, and enables the DeTrade observer. A usable DeTrade token is optional for HYBRID operation; without it the web scan uses manual fallback.

## Market Data Ownership

- Binance Spot BTCUSDT provides external prediction/reference data.
- BC.GAME Start Rate / End Rate remains product outcome truth.
- DeTrade provides round identity and timing only.
- PostgreSQL owns users, approvals, operational state, compact signal records, synchronized round records, broadcasts, and audit state.
- Raw exchange streams and DeTrade authorization secrets are not persisted.

Recent trade-flow samples are optional prediction evidence. Their count/span is visible diagnostically but is not a hard signal-readiness gate.

## Concurrency and Load

- market streams are process-wide, not per Telegram user;
- DeTrade observation is process-wide;
- scan computation is briefly locked/coalesced;
- per-user cooldown prevents scan spam;
- webhook concurrency/backpressure limits incoming work;
- webhook update IDs are idempotently claimed;
- final signal persistence uses row locking to prevent overlapping current user signals.

## Failure Behavior

- stale/missing Binance snapshot → UNAVAILABLE;
- insufficient closed candle history → UNAVAILABLE;
- weak/conflicting original intelligence → NO_TRADE;
- synchronized BC.GAME frame says unsafe → no actionable delivery;
- HYBRID + unavailable/expired DeTrade authorization → manual Scan Now fallback;
- AUTO + unavailable authorization → fail closed;
- blocked/unapproved user or disabled signal switch → no signal.

Background-worker health is monitored for background operations, but it is not an artificial gate on a healthy web-process prediction path.

There is no automatic order placement, BCGAME password handling, Martingale, loss chasing, or money movement.
