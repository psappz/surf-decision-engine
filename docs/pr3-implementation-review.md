# PR 3 implementation review

## Scope delivered

Implemented the Surf Decision Engine Consensus Engine in shadow mode. It reads immutable Forecast Ledger provider points, selects eligible inputs for a forecast cutoff, writes versioned append-only `consensus_runs` and `consensus_forecast_points`, and exposes manual CLI inspection/execution.

## Schema decision

Existing PR #1 schema was not sufficient for PR #4-ready typed queries because `consensus_forecast_points` only contained core wave/wind/tide columns. Added non-destructive Alembic revision `0006_consensus_fields` for swell, wind-wave, gust, water temperature and current fields.

## Provider input coverage

Copernicus Marine covers wave/swell/wind-wave fields. Open-Meteo Marine covers secondary marine, water temperature and currents. Open-Meteo Weather covers wind speed/direction/gust. IPMA remains direct-hourly weight zero and corroboration-only.

## Field-weight decisions

Provider weights are stored by normalized field in `ConsensusConfiguration`; no global provider weight is used.

## Time-alignment decision

Consensus v1 requires exact `valid_at` matching. No interpolation is performed, and no fake high-frequency Copernicus or IPMA values are invented.

## Spatial-relevance decision

A bounded distance factor uses selected/requested coordinates when present. It does not apply exposure, shelter, bathymetry, tide suitability or breaking-wave transformation.

## Statistical methods

Scalar values use validated weighted aggregation with weighted-median robust center and configurable outlier downweighting. Direction values use circular weighted vector averaging and resultant-vector magnitude.

## Idempotency

Equivalent completed runs are reused using a stable input fingerprint that includes cutoff, scope, engine version, configuration hash and selected provider point IDs. Forced recalculation can append a new equivalent run only when explicitly requested.

## Performance

Local smoke fixture: 99 provider input points, three provider runs, 11 active spots, three valid times, 33 consensus points written in 0.0587 seconds on SQLite.

## Runtime compatibility

No route, template, runtime forecast, scoring, daypart or recommendation read path was switched to consensus. Shadow data are only written/read by the new service and CLI.

## Test coverage

Covered scalar aggregation, circular directions, freshness, historical cutoff exclusion, completeness/idempotency/append-only behavior, IPMA zero direct hourly weight, sample-point de-duplication, stable configuration hash, app shadow compatibility and full regression.

## Documentation completeness

Created all mandatory consensus docs and updated existing operational/architecture docs with shadow-mode links.

## Remaining risks

- Equivalent-run reuse is metadata-based, not protected by a dedicated database unique constraint; concurrent identical automatic jobs could still race if auto-triggering is enabled later.
- IPMA corroboration is represented by policy/config and zero direct weight; no production IPMA corroboration data exists yet.
- No interpolation is implemented in v1.
- Query-count instrumentation is not separately measured; duration and point counts are measured.

## Follow-up requirements

PR #4 should implement Spot Intelligence using typed consensus fields. Later PRs should implement Recommendation and Confidence engines, add stronger automatic-trigger orchestration and complete a validation period before any UI read-path migration.

## Merge recommendation

READY TO MERGE WITH NOTED FOLLOW-UP
