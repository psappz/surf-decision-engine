# Consensus Engine audit

Product: Surf Decision Engine. Repository: surf-decision-engine.

## Available provider ledger inputs

Provider ingestion now writes immutable `provider_publications`, `provider_fetches`, `forecast_runs`, and `provider_forecast_points`. Runtime `/surf` views still read the existing runtime forecast tables. Ledger points are append-only rows keyed by forecast run, spot, sample point and `valid_at`.

Copernicus ledger points contain wave fields: total wave height/direction/period, swell height/direction/period, and wind-wave height/direction/period. PR #2 also preserves requested and selected grid coordinates in raw values for spatial relevance. Open-Meteo Marine points contain marine fields such as wave, swell, wind-wave, sea-surface temperature and current values. Open-Meteo Weather points contain wind speed, direction and gust. IPMA remains disabled/prepared and does not provide compatible exact hourly ledger points.

## Existing consensus schema

PR #1 introduced `consensus_runs` and `consensus_forecast_points`. Runs store calculated time, forecast cutoff, engine version, configuration hash, status, error and metadata. Points store one row per run/spot/valid_at with core typed forecast columns, provider count, quality scores and provenance JSON.

## Provider field coverage

- Copernicus: primary wave/swell/wind-wave provider; no local wind weight.
- Open-Meteo Marine: secondary marine provider and source for water/current fields.
- Open-Meteo Weather: primary local wind provider.
- IPMA: corroboration only; direct hourly weights are zero.

## Spatial resolution differences

Copernicus is a gridded offshore product; Open-Meteo is request-location based; IPMA regional daily ranges are not spot/hour exact. The consensus layer may apply bounded spatial relevance but must not model beach exposure, bathymetry, tide suitability or breaking-wave transformation.

## Temporal resolution differences

Consensus v1 uses exact `valid_at` matching only. It does not interpolate Copernicus PT3H data into fake hourly values. Future interpolation must be field-specific, versioned, recorded in provenance and quality-adjusted.

## Issue time, horizons and freshness

`forecast_runs.issued_at`, `fetched_at` and point `valid_at` are distinct. Reproducible historical selection must obey `forecast_cutoff_at`: data issued or fetched after the cutoff is invisible. Freshness combines source age, model-cycle age and forecast horizon through documented linear decay functions.

## Missing values and directions

Nulls remain null and are recorded. Invalid scalar values are excluded. Direction fields use circular statistics, never arithmetic degree means. Opposing vectors can cancel and produce a null direction consensus with low agreement.

## IPMA limitations

IPMA is not activated. PR #3 must not fabricate hourly IPMA points. Future daily regional ranges may only corroborate compatible hourly providers unless IPMA later supplies exact compatible values.

## Current runtime source of truth

The runtime source of truth remains the existing runtime forecast tables, recommendation calculation and templates. Consensus writes are shadow outputs only.

## Proposed consensus lifecycle

A request selects eligible provider ledger points for a cutoff/scope, hashes configuration and selected inputs, reuses an equivalent completed run when allowed, otherwise creates a running run, batch-inserts points, and marks the run completed. Failure rolls back point inserts and records bounded non-secret error information where possible.

## Trigger points

PR #3 exposes manual CLI execution and configuration flags. Automatic ingestion-triggered consensus remains disabled by default and should be debounced before production activation.

## Concurrency and idempotency risks

Equivalent-run reuse relies on a stable input fingerprint in run metadata rather than a dedicated unique constraint. Concurrent identical CLI executions could race and produce two equivalent runs; this is acceptable for shadow PR #3 and should be hardened with a database constraint or queue if automatic production triggering is enabled.

## Schema sufficiency

The PR #1 consensus point schema had only core fields. PR #3 requires typed queryable columns for swell, wind-wave, gust, water temperature and currents so future Spot Intelligence can query them without parsing JSON. A non-destructive `0006_consensus_fields` migration is required.

## Explicit PR #3 exclusions

No Spot Intelligence, Recommendation Engine migration, final Confidence Engine, Observation Engine, UI read-path switch, scheduler replacement, IPMA activation, deployment or production data modification.

## Follow-up requirements

PR #4 should consume typed consensus fields for Spot Intelligence. Later PRs should migrate Recommendation and Confidence separately, add stronger concurrent idempotency, decide on versioned interpolation, and run a validation period before any UI read-path migration.
