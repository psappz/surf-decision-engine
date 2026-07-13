# Provider ledger migration audit

## 1. Current provider architecture
Surf Decision Engine has two provider paths. The protected fixture/Open-Meteo-style bundle in `app/forecast_service.py` writes current `marine_forecasts`, `weather_forecasts`, and `tide_forecasts` rows from one `provider_fetches` bundle. Copernicus has a publication-aware background path in `app/copernicus_jobs.py` with catalogue detection, job leasing, NetCDF download, validation, normalization, current forecast writes, and recommendation recalculation. IPMA is intentionally disabled and returns no points.

## 2. Provider entry points
- Open-Meteo-style runtime fixture: `ensure_seed_forecasts`.
- Copernicus scheduler/tooling: `app.tools.copernicus`, `app.workers.copernicus`, and `ingest_job`.
- Provider adapter shells: `app/providers.py`.
- Health/status: `provider_status`.

## 3. Scheduler and worker ownership
Copernicus remains owned by the existing cron/tool/worker queue. Page rendering must not start provider downloads. The fixture/Open-Meteo path remains protected by the existing 30-minute provider bundle limit.

## 4. Current runtime tables
Current reads still use `provider_fetches`, `marine_forecasts`, `weather_forecasts`, `tide_forecasts`, `spot_scores`, and `daily_recommendations`.

## 5. Current update and upsert behavior
The current forecast tables append rows and read latest rows by provider/time. Recommendations are recalculated from current runtime tables. PR 2 does not switch reads to ledger tables.

## 6. Current provider error handling
Copernicus marks job/publication state failed or degraded. The fixture path marks provider fetch status. Ledger failure while enabled is surfaced as `ledger_failed` metadata rather than silently reporting complete success.

## 7. Current retry behavior
Copernicus job acquisition increments attempts and uses lease state. Ledger fetch attempts increment per provider publication and are protected by a unique `(publication_id, attempt_number)` constraint.

## 8. Current publication detection
Copernicus already detects publication identity from product, dataset, model cycle, latest forecast timestamp, and catalogue fingerprint. Open-Meteo lacks a strong issue timestamp in the current implementation, so the new identity builder uses request scope plus issue metadata or bounded content hash. IPMA identities are prepared per feed/location/date/update.

## 9. Proposed dual-write insertion points
- After current Open-Meteo-style fixture rows are staged and before success commit.
- After Copernicus NetCDF validation/normalization and current forecast rows are staged, before job success is committed.
- IPMA remains disabled; only deterministic identity support and documentation are added.

## 10. Transaction boundaries
Ledger writes use one nested transaction for publication, fetch, forecast run, and batched points. The current runtime transaction remains the operational success boundary. No distributed transaction is attempted across downloads and database writes.

## 11. Idempotency risks
Open-Meteo fallback identities depend on request scope and bounded content hash when no issue time is available. Copernicus identities must not use fetched time. Duplicate points inside one run rely on database uniqueness and rollback.

## 12. Concurrency risks
Copernicus retains the existing job lease. Fetch attempt allocation uses database uniqueness as final protection. A future PostgreSQL-specific lock can be added if concurrent retries become common.

## 13. Raw-payload storage
Copernicus stores filesystem NetCDF references, checksum, and size. Small JSON payloads use deterministic gzip files under `data/provider-raw/<provider>/` with checksums and no secrets.

## 14. Provider-specific publication identity
Copernicus: product, dataset, model cycle, latest valid time, catalogue metadata fingerprint. Open-Meteo Marine/Weather: provider, request scope, issue/update metadata or bounded content hash. IPMA: feed type, endpoint, dataUpdate, forecastDate, location, category.

## 15. Fields that cannot yet be represented cleanly
IPMA daily sea ranges cannot be represented as truthful hourly `provider_forecast_points` without information loss. PR 2 therefore does not generate fake hourly IPMA points.

## 16. Explicit exclusions from PR 2
No Consensus, Spot Intelligence, Recommendation, Confidence, current views, history UI, backfill, raw cleanup, deployment, or read-path switch.

## 17. Recommended follow-up work for PR 3
Implement Consensus Engine consumption of provider ledger runs, then review current views and history UI separately.
