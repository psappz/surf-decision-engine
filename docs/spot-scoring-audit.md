# Spot Scoring foundation audit (PR #5 Slice 1)

## Boundary

This slice establishes provenance, lifecycle, validation, and query foundations for the append-only Spot Scoring stage. It does not calculate a total score, classify conditions, rank spots, generate recommendations, read from runtime forecast tables, expose UI, register a scheduler, or alter deployment/provider paths. Existing `app/scoring.py` remains evidence only and is not modified or called by this foundation.

## Input and output identity

A `spot_score_run` identifies:

- one immutable `spot_assessment_run`;
- scoring engine version and behavior-only canonical configuration hash;
- surfer profile version and behavior-only canonical profile hash;
- canonical selected assessment-point scope hash;
- nonnegative append-only recalculation sequence.

Attempt zero is the legacy/ordinary attempt. Positive sequences permit failed retries and future explicit reruns without overwriting history. The database uniqueness key is the final concurrency guard.

Each `spot_score_snapshot` has a non-null `assessment_point_id` with `ON DELETE RESTRICT`. The repository additionally verifies that the point belongs to the score run's assessment input and that its spot/time identity exactly matches the snapshot. A batch must target one running score run and cannot reference a point twice.

## Lifecycle and repository safety

Runs can only be created as `running`. A conditional update permits exactly one transition from `running` to `completed` or `failed`. Snapshot insertion is running-only. Persisted errors pass through shared bounded secret/e-mail redaction. Equivalent-completed and latest-attempt lookups, next-sequence allocation, direct gets, counts, and deterministic bounded lists support later service/CLI work without relaxing lifecycle guarantees.

The repository boundary is append-only; no cross-dialect trigger is claimed. Concurrent sequence allocation must still handle the unique constraint as the authoritative race guard.

## Canonical provenance types

`SpotScoringConfiguration` and `SurferProfileSnapshot` are frozen validated values. Their `effective_values()` are canonicalized to the same practical numeric representation used by their SHA-256 hashes. Engine/profile versions and profile names are persisted separately and excluded from behavior hashes. Booleans are not accepted as numbers; non-finite numbers, unordered or incomplete bounds, invalid versions, and unknown profiles fail closed.

The profile snapshots preserve only the directly evidenced physical wave/period ranges from the application's existing selectable proficiency categories. Legacy hazard penalties and advanced-fit points are intentionally omitted: converting them into normalized tolerances or new deductions would invent product semantics. Hazard handling, technical-spot behavior, factor weights, missing-data policy, classification thresholds, and `safety_score` semantics remain explicit product gates. This slice does not define how any profile field contributes to a score.

## Migration and legacy data

Migration `0008_spot_scoring_foundation` gives existing score runs safe defaults:

- `calculation_scope_hash = 'legacy-unscoped'`;
- `recalculation_sequence = 0`.

Existing score snapshots are backfilled only when their unique score-run assessment input plus spot/time identity resolves to an assessment point. Upgrade deliberately fails with a bounded operator-facing message rather than inventing provenance for unmatched legacy rows.

Downgrade to `0007` is **data-dependent** after multiple scopes or recalculation attempts exist: `0007`'s narrower uniqueness cannot represent those rows. Operators must retain `0008` or explicitly resolve duplicate score-run identities before downgrade. Dropping `assessment_point_id` itself loses the stronger provenance link and must be treated as an intentional rollback.

## Database defenses

The migration adds:

- nonnegative recalculation-sequence check;
- input + scope + sequence uniqueness and 80-character engine/profile version parity;
- run status/input/equivalence indexes;
- restrictive typed assessment-point foreign key and per-run point uniqueness;
- per-component `0..100` checks, existing total-score `0..100` check, and nonnegative penalty check;
- run, assessment-point, and spot/time snapshot indexes.

No total score formula or scoring policy is present.
