# Append-only forecast ledger

This PR adds the storage foundation for immutable forecast history in Surf Decision Engine. It does not connect provider ingestion, scoring, recommendation reads, UI, scheduler, or deployment code to the new tables.

## Principle

Forecast information is immutable. A new provider publication, fetch attempt, normalization pass, engine calculation, or recommendation generation creates new rows. Existing history rows are not updated to represent newer conditions.

Status fields may describe run lifecycle, but point and snapshot records are owned by a run and should not be overwritten.

## Ledger hierarchy

```text
Provider Publication
↓
Provider Fetch
↓
Forecast Run
↓
Provider Forecast Points
↓
Consensus Run
↓
Consensus Forecast Points
↓
Spot Assessment Run
↓
Spot Assessment Points
↓
Spot Score Run
↓
Spot Score Snapshots
↓
Confidence Run
↓
Confidence Snapshots
↓
Recommendation Snapshots
```

## Tables

### Provider Engine

- `provider_publications`: generic immutable publication identity and lifecycle metadata.
- `provider_fetches`: existing fetch table extended with nullable ledger columns for publication ownership, attempts, checksums, raw payload paths, deletion metadata, and normalized record counts. PR 2 dual-write support populates these fields only when `PROVIDER_LEDGER_WRITES_ENABLED=true`.
- `forecast_runs`: one normalization run for a provider fetch and normalizer version.
- `provider_forecast_points`: typed, run-owned provider forecast values.

`provider_forecast_points` is unique by `forecast_run_id`, `spot_id`, `sample_point_id`, and `valid_at`. There is intentionally no uniqueness on only `spot_id` and `valid_at`, so multiple model runs for the same valid time can coexist.

### Consensus stage

- `consensus_runs`
- `consensus_forecast_points`

### Spot Intelligence stage

- `spot_assessment_runs`
- `spot_assessment_points`

### Recommendation stage

- `spot_score_runs`
- `spot_score_snapshots`
- `recommendation_snapshots`

`recommendation_snapshots` intentionally allows multiple rows for the same date and daypart.

### Confidence stage

- `confidence_runs`
- `confidence_snapshots`

## Time semantics

The ledger keeps these meanings separate:

- `issued_at`: provider/model issue or cycle time.
- `fetched_at`: when Surf Decision Engine fetched or received the payload.
- `valid_at`: the target forecast time represented by a point or snapshot.

All application-supplied timestamps are expected to be timezone-aware UTC values.

## Run ownership

Every point or snapshot belongs to a parent run:

- provider point → forecast run
- consensus point → consensus run
- spot assessment point → assessment run
- score snapshot → score run
- confidence snapshot → confidence run
- recommendation snapshot → generated recommendation row with references to contributing run IDs where available

## Compatibility

Current runtime tables and read paths remain in place:

- current provider ingestion still writes existing forecast tables;
- current scoring still writes current score/recommendation tables;
- current pages still read current tables;
- no provider job is dual-writing yet.
