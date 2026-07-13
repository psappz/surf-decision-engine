# Forecast versioning

Append-only history requires explicit version metadata on every run. Versions make later recommendations reproducible and distinguish data changes from algorithm changes.

## Required timestamp separation

- `issued_at`: provider model cycle or publication issue time.
- `fetched_at`: time the payload was fetched by Surf Decision Engine.
- `valid_at`: forecast target time.

These timestamps must not be collapsed into one field. A model issued at 00:00, fetched at 01:10, and valid for 09:00 is one historical version. A later model run for the same valid time is a different version.

## Provider and normalizer versioning

`forecast_runs` stores:

- `schema_version`
- `normalizer_version`
- `normalizer_configuration_hash`
- `geographic_bounds_json`
- `temporal_bounds_json`
- `status`
- `error_message`

The same fetch may be normalized more than once with different normalizer code or configuration. The table enforces uniqueness on `fetch_id`, `normalizer_version`, and `normalizer_configuration_hash`. The configuration hash covers field mappings, unit conversions, sampling-point selection, interpolation policy, and missing-value handling when those are driven by configuration rather than code.

## Consensus versioning

`consensus_runs` stores:

- `consensus_engine_version`
- `configuration_hash`
- `forecast_cutoff_at`

A consensus run must declare which provider forecast versions were eligible by cutoff and configuration.

## Spot Intelligence versioning

`spot_assessment_runs` stores:

- `spot_rules_version`
- `spot_rules_hash`
- `spot_intelligence_engine_version`
- `configuration_hash`

The rules hash protects reproducibility when spot metadata or rule text changes under the same human-readable version. `configuration_hash` is separate and covers global Spot Intelligence transformation settings so the rules hash does not carry two meanings.

## Recommendation scoring versioning

`spot_score_runs` stores:

- `scoring_engine_version`
- `scoring_configuration_hash`
- `surfer_profile_version`
- `surfer_profile_hash`

Score snapshots are immutable outputs of that scoring run. The profile hash captures the exact profile configuration when the same human-readable profile version is edited or externalized.

## Confidence versioning

`confidence_runs` stores:

- `confidence_engine_version`
- `configuration_hash`
- `forecast_cutoff_at`

Confidence snapshots preserve score components and reasons separately from spot scores.

## Recommendation snapshot versioning

`recommendation_snapshots` stores references to contributing run IDs and engine versions when available:

- `forecast_run_ids_json`
- `consensus_run_id`
- `assessment_run_id`
- `score_run_id`
- `confidence_run_id`
- `spot_rules_version`
- `scoring_engine_version`
- `confidence_engine_version`
- `surfer_profile_version`

Multiple recommendation snapshots for the same date and daypart are valid. They represent distinct generations, not updates.

## PR 2 provider ledger dual-write note

Surf Decision Engine provider ingestion can dual-write successful provider runs into the append-only Forecast Ledger when `PROVIDER_LEDGER_WRITES_ENABLED=true`. The default remains disabled for production-style environments. Current runtime tables, recommendations, scoring, scheduler ownership, and UI read paths remain unchanged. See `docs/provider-ledger-writes.md`, `docs/provider-data-mapping.md`, and `docs/provider-ledger-failure-recovery.md` for the PR 2 implementation details.


## Consensus Engine shadow mode

PR #3 adds a versioned, append-only Consensus Engine in shadow mode. It reads immutable Forecast Ledger provider points and writes `consensus_runs` / `consensus_forecast_points`; current UI, runtime forecasts and recommendations remain unchanged. See `docs/consensus-engine.md` and `docs/consensus-operations.md`.
