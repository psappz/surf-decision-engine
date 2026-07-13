# History architecture audit

This audit records the pre-ledger forecast architecture before adding append-only historical storage for Surf Decision Engine.

## Current forecast flow

1. The FastAPI app starts and creates current schema objects via SQLAlchemy metadata for local development.
2. Seeded surf spots are stored in `surf_spots`.
3. A protected provider bundle writes current-style forecast rows into:
   - `marine_forecasts`
   - `weather_forecasts`
   - `tide_forecasts`
4. Scoring reads those current-style rows by spot and time window.
5. Recommendation calculation writes `spot_scores` and `daily_recommendations`.
6. Authenticated pages read current recommendations and request-time rankings from existing tables.

## Current provider flow

### Fixture and local providers

- `provider_fetches` stores provider-bundle status and a raw JSON response envelope.
- `marine_forecasts`, `weather_forecasts`, and `tide_forecasts` store normalized values as JSON by provider, spot, and forecast time.
- The local tide provider is calculated inside the app and stored with the same current-style forecast table shape.

### Copernicus scheduler and worker

- `copernicus_publications` records provider-specific publication detection and ingestion state.
- `copernicus_ingestion_jobs` queues and leases background ingestion jobs.
- The worker downloads a raw file, validates it, parses it per spot, writes `marine_forecasts`, updates publication/job status, and recalculates current recommendations.
- Raw-file cleanup retains recent successful files and old temporary files.

### Disabled or placeholder providers

- IPMA is intentionally disabled and does not write current forecasts.
- Webcam and buoy confirmation are not currently ingested into scoring tables.

## Current overwrite behavior

The runtime currently preserves many provider rows, but recommendation outputs are current-state oriented:

- `calculate_recommendations` deletes `daily_recommendations` for the target date.
- It also deletes `spot_scores` for the target date.
- New current recommendation rows are then inserted.
- Request-time rankings are calculated in memory and are not persisted as historical versions.
- Current forecast table readers choose latest rows per provider/time and do not expose immutable run ownership.

This means historical recommendation reproducibility is not guaranteed by current tables alone.

## Existing reusable tables

- `surf_spots`: canonical spot dimension for ledger foreign keys.
- `users`, `sessions`, auth/audit tables: not part of forecast history but should remain untouched.
- `copernicus_publications`: provider-specific predecessor to generalized `provider_publications`; it remains in place for existing ingestion.
- `provider_fetches`: current provider bundle table. It can be extended non-destructively with nullable ledger columns for generic fetch attempts.
- `marine_forecasts`, `weather_forecasts`, `tide_forecasts`: current read-path tables. They should remain unchanged for production behavior.
- `spot_scores`, `daily_recommendations`: current recommendation tables. They should remain unchanged; ledger snapshots are separate.

## Conflicts and gaps

- Current provider fetches do not belong to a generic publication record.
- Current forecast points do not belong to an immutable forecast run.
- Current forecast uniqueness is not run-scoped.
- Current recommendation rows are overwritten by date and are not immutable snapshots.
- Copernicus publication state combines publication, fetch, raw payload, and ingestion status concepts that the ledger separates.
- Existing JSON value blobs are convenient for current UI but insufficient for typed historical analytics.
- Existing timestamps include fetched and forecast time, but do not consistently separate `issued_at`, `fetched_at`, and `valid_at` across every stage.

## Migration risks

- The existing `provider_fetches` table is active in production; ledger columns must be nullable and additive.
- New tables must not change provider ingestion, recommendation calculation, UI, worker behavior, scheduler behavior, or deployment files.
- Foreign keys to `surf_spots` should preserve history and avoid cascade deletion.
- SQLite tests must remain functional even where PostgreSQL later uses stronger JSONB/index semantics.
- `sample_point_id` needs a deterministic non-null sentinel for uniqueness so duplicate rows are rejected consistently when no sample point is available.

## Mapping into the append-only architecture

| Current concept | Ledger concept | PR 1 action |
| --- | --- | --- |
| Provider-specific publication tracking | `provider_publications` | Add generic table; keep existing provider-specific table untouched. |
| Provider bundle/fetch rows | `provider_fetches` | Extend current table with nullable ledger attempt columns. |
| Normalized provider write | `forecast_runs` | Add immutable run table. |
| Marine/weather/tide forecast rows | `provider_forecast_points` | Add typed immutable point table; do not wire current ingestion yet. |
| In-memory/current provider merging | `consensus_runs`, `consensus_forecast_points` | Add storage only. |
| Spot-local interpretation in scoring functions | `spot_assessment_runs`, `spot_assessment_points` | Add storage only. |
| Current score rows | `spot_score_runs`, `spot_score_snapshots` | Add immutable score snapshots; keep current scores untouched. |
| Existing confidence labels | `confidence_runs`, `confidence_snapshots` | Add explicit confidence history. |
| Current daily recommendations | `recommendation_snapshots` | Add immutable recommendation history without replacing current table. |

## Follow-up for PR 2

- Dual-write provider publications and fetch attempts into the generic ledger.
- Dual-write provider normalized points into forecast runs and provider forecast points.
- Keep current tables populated until read-path migration is complete.
- Add current-state SQL views only after ledger writes are proven.
- Migrate recommendation generation to write immutable snapshots while preserving existing UI behavior.
- Add historical backfill only from real stored provider data; never fabricate history.
