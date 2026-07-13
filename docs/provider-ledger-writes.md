# Provider ledger writes

Provider ingestion dual-writes to the append-only Forecast Ledger only when `PROVIDER_LEDGER_WRITES_ENABLED=true`. Runtime tables remain active and current UI reads are unchanged.

## Sequence

```text
Provider Scheduler
→ Provider Adapter / worker
→ Normalize
→ Legacy Runtime Write
→ Provider Ledger Writer
→ Provider Publication
→ Provider Fetch
→ Forecast Run
→ Provider Forecast Points
→ Provider Job Success
```

## Tables
Current runtime tables continue to serve `/surf`, recommendations, admin/moderation pages, and health status. Ledger tables become historical storage for publications, fetch attempts, runs, and immutable points.

## Transaction boundaries
`ProviderLedgerWriter` writes a publication, fetch attempt, forecast run, and points in one nested database transaction. It does not commit once per point.

## Feature flag
- `false`: provider behavior is unchanged.
- `true`: ingestion writes both current runtime rows and ledger rows.

## Idempotency and retries
Publication identity is deterministic. Fetch attempts increment under the publication. Forecast runs are scoped by fetch, normalizer version, and normalizer configuration hash. Point uniqueness is scoped to run/spot/sample/valid time.

## Partial success
If runtime persistence succeeds but ledger persistence fails while enabled, the provider job does not silently report complete success. The failure is recorded as `ledger_failed` metadata and the previous successful data remains intact.

## Why reads remain unchanged
PR 2 is a migration write path only. PR 3 will implement Consensus Engine use of ledger data.
