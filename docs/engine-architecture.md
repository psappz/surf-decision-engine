# Engine architecture

Surf Decision Engine separates historical forecast processing into four engines. This PR adds schema, models, repositories, and tests only. It does not implement calculations or change production behavior.

## 1. Provider Engine

Responsibilities:

- discover provider publications;
- download provider payloads;
- validate payload integrity;
- archive raw payload metadata;
- normalize provider values;
- create forecast runs and provider forecast points.

The Provider Engine never evaluates surf spots and never creates recommendations.

Storage:

- `provider_publications`
- `provider_fetches`
- `forecast_runs`
- `provider_forecast_points`

## 2. Spot Intelligence Engine

Responsibilities:

- transform offshore and provider-normalized conditions into local surf characteristics;
- evaluate swell direction fit, height fit, period fit, wind protection, exposure, tide suitability, breaking-wave estimates, hazards, and uncertainty factors.

The Spot Intelligence Engine never ranks spots.

Storage:

- `spot_assessment_runs`
- `spot_assessment_points`

## 3. Recommendation Engine

Responsibilities:

- produce surf scores;
- rank candidate spots;
- generate morning, midday, and evening recommendation snapshots;
- preserve enough input/run metadata to reproduce why a recommendation was generated.

Storage:

- `spot_score_runs`
- `spot_score_snapshots`
- `recommendation_snapshots`

## 4. Confidence Engine

Responsibilities:

- evaluate provider agreement;
- evaluate data freshness;
- evaluate data completeness;
- evaluate forecast stability;
- evaluate spatial relevance and spot predictability;
- produce `confidence_score`, `confidence_label`, and `confidence_reasons`.

Storage:

- `confidence_runs`
- `confidence_snapshots`

## Boundary rules

- Provider Engine does not rank or recommend.
- Spot Intelligence Engine does not rank.
- Recommendation Engine consumes assessment and confidence output; it does not fetch providers.
- Confidence Engine records evidence and reasons separately from score snapshots.

## Current PR boundary

This PR creates the storage model and repository API only. Provider ingestion, calculation engines, current-state views, analytics, history UI, backfill, and production deployment are intentionally out of scope.

## PR 2 provider ledger dual-write note

Surf Decision Engine provider ingestion can dual-write successful provider runs into the append-only Forecast Ledger when `PROVIDER_LEDGER_WRITES_ENABLED=true`. The default remains disabled for production-style environments. Current runtime tables, recommendations, scoring, scheduler ownership, and UI read paths remain unchanged. See `docs/provider-ledger-writes.md`, `docs/provider-data-mapping.md`, and `docs/provider-ledger-failure-recovery.md` for the PR 2 implementation details.


## Consensus Engine shadow mode

PR #3 adds a versioned, append-only Consensus Engine in shadow mode. It reads immutable Forecast Ledger provider points and writes `consensus_runs` / `consensus_forecast_points`; current UI, runtime forecasts and recommendations remain unchanged. See `docs/consensus-engine.md` and `docs/consensus-operations.md`.
