# Forecast ledger PR 1 review

Review target: local branch `feature/forecast-ledger-schema`, starting tip `ce991ef`.

Scope: architectural review of the PR 1 storage foundation only. This review does not implement provider wiring, derived calculations, UI, deployment, or PR 2 behavior.

## 1. `provider_fetches` responsibility review

### Inspected

- `app/models.py`
- `alembic/versions/0005_forecast_ledger.py`
- `app/repositories/provider_fetch_repository.py`
- `app/forecast_ledger_repository.py` compatibility facade
- `tests/test_forecast_ledger.py`
- Existing pre-ledger uses in `app/forecast_service.py` and `app/copernicus_jobs.py`

### Result

`provider_fetches` passes the limited-responsibility review for PR 1.

The table represents a fetch/processing attempt. The new generic ledger fields are operational fetch metadata:

- `publication_id`
- `started_at`
- `completed_at`
- `attempt_number`
- `download_size_bytes`
- `payload_checksum`
- `raw_payload_path`
- `raw_file_deleted_at`
- `normalized_records_count`
- `error_code`
- `error_message`
- `metadata_json`
- `created_at`
- `updated_at`

The table does not contain forecast-domain values such as wave height, wave period, valid forecast time, consensus values, spot scores, confidence scores, or recommendations. Those values are stored in run-scoped append-only ledger tables.

### Legacy compatibility and ambiguity

Pre-ledger code already uses `provider_fetches` for bundle-level provider status records. Existing legacy fields remain:

- `provider_name`
- `fetched_at`
- `latitude`
- `longitude`
- `status`
- `raw_response`
- `parsing_errors`
- `data_age_seconds`

These fields are not forecast measurements. `latitude` and `longitude` can be read as a legacy fetch target coordinate, but current Copernicus/Open-Meteo paths write `None` for bundle fetches. Removing or renaming them now would be a production migration risk, so they remain for compatibility.

The new fields are nullable and the uniqueness constraint is scoped to `(publication_id, attempt_number)`. Legacy fetch rows with `publication_id IS NULL` remain valid in both SQLite and PostgreSQL because nullable unique columns do not collapse all legacy rows into one record.

Decision: keep the existing table and document the dual legacy/generic meaning. PR 2 should migrate provider wiring gradually by writing `publication_id`, `attempt_number`, and timing/checksum fields for new generic fetch attempts while leaving legacy readers intact.

## 2. Repository organization review

### Original file metrics before correction

`app/forecast_ledger_repository.py` before this review:

- line count: 170
- public repository functions: 21
- logical domains represented: 9
  - provider publications
  - provider fetches
  - forecast runs
  - provider forecast points
  - consensus runs and points
  - spot-assessment runs and points
  - spot-score runs and snapshots
  - confidence runs and snapshots
  - recommendation snapshots
- dependency structure: one module imported every ledger model plus `ProviderFetch`
- transactional helper sharing: only simple `utc_now`, `db.add`, `db.add_all`, and `db.flush` patterns

### Decision

A split is justified before provider ingestion is added.

Reasoning:

- The single file already spans every future engine boundary.
- PR 2 provider wiring should not need to import consensus, scoring, confidence, or recommendation helpers.
- The shared code is minimal, so splitting does not require a generic repository framework.
- Import compatibility is preserved with a facade at `app/forecast_ledger_repository.py`.

### Resulting structure

```text
app/repositories/
    __init__.py
    ledger_utils.py
    provider_publication_repository.py
    provider_fetch_repository.py
    forecast_repository.py
    consensus_repository.py
    spot_assessment_repository.py
    spot_score_repository.py
    confidence_repository.py
    recommendation_repository.py
```

`app/forecast_ledger_repository.py` now re-exports the public functions for compatibility.

### Resulting metrics

| File | Lines | Public functions |
| --- | ---: | ---: |
| `app/forecast_ledger_repository.py` | 38 | 0 direct definitions; compatibility re-exports |
| `app/repositories/provider_publication_repository.py` | 34 | 3 |
| `app/repositories/provider_fetch_repository.py` | 40 | 2 |
| `app/repositories/forecast_repository.py` | 43 | 5 |
| `app/repositories/consensus_repository.py` | 22 | 2 |
| `app/repositories/spot_assessment_repository.py` | 22 | 2 |
| `app/repositories/spot_score_repository.py` | 22 | 2 |
| `app/repositories/confidence_repository.py` | 22 | 2 |
| `app/repositories/recommendation_repository.py` | 18 | 2 |
| `app/repositories/ledger_utils.py` | 7 | 1 |

No abstract base classes or generic repository framework were introduced.

## 3. Version/hash matrix

| Run type | Engine/version field | Configuration hash | Input cutoff/reference | Review result |
| --- | --- | --- | --- | --- |
| Forecast run | `normalizer_version` | `normalizer_configuration_hash` | `publication_id`, `fetch_id`, `issued_at`, `fetched_at` | Added separate hash so configuration-only normalization changes are reproducible. |
| Consensus run | `consensus_engine_version` | `configuration_hash` | `forecast_cutoff_at` | Already present and retained. |
| Spot assessment run | `spot_intelligence_engine_version`, `spot_rules_version` | `spot_rules_hash`, `configuration_hash` | `consensus_run_id` | Added separate engine configuration hash so spot rules and global transformation settings are not overloaded. |
| Spot score run | `scoring_engine_version`, `surfer_profile_version` | `scoring_configuration_hash`, `surfer_profile_hash` | `assessment_run_id` | Added profile hash so mutable/externalized profile content is distinguishable from the label/version. |
| Confidence run | `confidence_engine_version` | `configuration_hash` | `forecast_cutoff_at` | Already present and retained. |
| Recommendation snapshot | Denormalized version labels: `spot_rules_version`, `scoring_engine_version`, `confidence_engine_version`, `surfer_profile_version` | No duplicated hashes | `forecast_run_ids_json`, `consensus_run_id`, `assessment_run_id`, `score_run_id`, `confidence_run_id` | Run references are sufficient for hashes; duplicating hashes would risk inconsistency. |

## 4. Ledger-context decision

Decision: A. Do not add a broad context type yet.

A broad `ForecastLedgerContext` would be premature in PR 1 because no provider wiring or multi-stage pipeline code exists yet. It would likely mix IDs from stages that are not created together and could become a mutable god object.

Preferred PR 2 direction:

- Provider normalization receives only publication/fetch inputs.
- Consensus receives selected forecast run IDs, cutoff, and consensus configuration.
- Spot assessment receives a consensus run and rule/config snapshot.
- Scoring receives assessment run, scoring config, and surfer profile snapshot.
- Confidence receives the forecast/consensus/spot references it actually needs.
- Recommendation receives score and confidence run references.

A small immutable correlation context may be considered later:

```python
@dataclass(frozen=True)
class LedgerExecutionContext:
    correlation_id: str
    triggered_at: datetime
```

Do not add it until at least two concrete services need the same correlation metadata.

## 5. Schema-integrity findings

- Deletion safety: new ledger foreign keys use `ondelete='RESTRICT'`, including surf spot references, so historical records are not intentionally cascade-deleted by spot administration.
- Run-scoped uniqueness: provider forecast point uniqueness is `(forecast_run_id, spot_id, sample_point_id, valid_at)`, not `(spot_id, valid_at)`, allowing multiple model runs for the same valid time.
- Nullable sample point behavior: `sample_point_id` is normalized to the empty string in models/repositories and migration defaults. This avoids PostgreSQL/SQLite nullable unique-column differences.
- Recommendation immutability: no uniqueness constraint exists on `(recommendation_date, daypart)`, so multiple generations per daypart are valid.
- Existing provider write paths: no existing production provider path imports the new repository modules. Current `forecast_service.py` and `copernicus_jobs.py` continue to write legacy current tables.
- Product-facing docs in changed files use Surf Decision Engine and do not introduce prohibited former product names.

## 6. Changes made during review

- Split the monolithic ledger repository into stage/domain repository modules.
- Kept `app/forecast_ledger_repository.py` as a compatibility facade.
- Added `normalizer_configuration_hash` to `forecast_runs`.
- Added `configuration_hash` to `spot_assessment_runs`.
- Added `surfer_profile_hash` to `spot_score_runs`.
- Updated uniqueness constraints so configuration-only changes create distinct run records.
- Updated tests for the new fields and repository facade compatibility.
- Updated `docs/forecast-versioning.md` to document the added hashes.

## 7. Deferred recommendations for PR 2

- Wire provider ingestion into `provider_publications`, `provider_fetches`, `forecast_runs`, and `provider_forecast_points` only; do not wire derived engines in the same PR.
- Backfill or dual-write from legacy current tables only after a separate migration plan is reviewed.
- Add provider-specific idempotency around publication detection and fetch attempt numbering.
- Consider a small immutable correlation context only after real services require common correlation metadata.
- Keep legacy current read models until current views are explicitly replaced by ledger-derived reads.
