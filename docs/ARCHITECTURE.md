# Architecture

## Runtime topology

```text
Telegram
  -> Render web: secret-validated FastAPI webhook
       -> access/onboarding/admin handlers
       -> UserSignalService
       -> shared DeTradeObserver (read-only round timing)
       -> shared Binance market cache + SignalIntelligenceService
       -> PostgreSQL

Render worker
  -> shared Binance market cache
  -> advisory-lock background coordinator
       -> signal lifecycle
       -> broadcast delivery
       -> verification-packet delivery
       -> retention cleanup
       -> PostgreSQL
```

The observer is process-wide, not user-scoped. Concurrent requests share its latest frame; cold probes are single-flight. Signal computation is also locked/coalesced briefly. Per-user cooldown, webhook concurrency limits, update idempotency, PostgreSQL row locking, and the unique current-signal index provide additional load and race protection.

## Timer decision path

1. The observer obtains ephemeral credentials from the configured provider.
2. It connects to the verified DeTrade WebSocket with token, `device`, account `type`, and browser-derived `cid` query parameters.
3. It sends the verified zlib-compressed subscription and five-second application heartbeat.
4. A frame is accepted only if it contains the complete round identity/status/time shape.
5. `priceStartTime` becomes a local monotonic deadline derived from `currentTime` at receipt.
6. The round service requires a fresh frame, status `1001`, a known round ID, at least the initial safety margin, and a five-second `priceStartTime → priceEndTime` window.
7. After the existing signal engine finishes, the monotonic deadline is checked again against the dispatch margin.
8. Only then may a signal record and Telegram response be created.

Known closed, late, stale, unknown, transition, or wrong-product frames are synchronized-but-not-actionable and cannot fall through to manual behavior. HYBRID fallback applies only when no authoritative frame can be obtained.

## Data ownership

- DeTrade owns BCGAME round identity and order-window timing.
- BCGAME Start/End Rate remains product outcome truth.
- Binance provides analysis and diagnostic reference data only.
- PostgreSQL owns users, approvals, operational state, compact signals, genuine synchronized round records for directional signals, broadcasts, and audit records.
- Raw market streams and DeTrade tokens are not persisted.

NO TRADE scans do not create BCGAME round rows. Verification account IDs and Telegram evidence file IDs are purged immediately after the owner decision. Temporary signal, webhook, notification, and broadcast-delivery records are cleaned after ten days.

## Failure behavior

- HYBRID + no/expired token: manual Scan Now fallback, no crash.
- AUTO + no token/observer: startup failure or no signal.
- Valid frame says unsafe: no fallback and no directional signal.
- Market/worker/access/kill-switch failure: no signal.
- Auth failure codes `603` or `3100`: clear the last observation, invalidate the provider, reconnect only after new credentials are supplied.
- Unknown DeTrade status, including cautious handling of `1008`: non-tradeable.

There is no automatic order placement, BCGAME password handling, Martingale, loss chasing, or money movement.
