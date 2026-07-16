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

Each run persists the canonical sorted assessment-point ID scope as JSON and derives its scope hash from that payload. Each `spot_score_snapshot` has a non-null `assessment_point_id` with `ON DELETE RESTRICT`. The repository additionally verifies that the point belongs to the score run's assessment input and canonical scope and that its spot/time identity exactly matches the snapshot. A batch must be non-empty, target one running score run, and cannot reference a point twice.

## Lifecycle and repository safety

Runs can only be created as `running`. Snapshot insertion and terminal transition use the same conditional no-op write gate, which serializes SQLite writers and obtains a row write lock on PostgreSQL. Completion additionally requires the persisted assessment-point set to exactly equal the canonical non-empty scope; empty, partial, extra, and substituted outputs cannot become reusable completed runs. A conditional terminal update permits exactly one transition from `running` to `completed` or `failed`. Persisted errors and metadata pass through bounded recursive secret/e-mail redaction. Equivalent-completed and latest-attempt lookups, next-sequence allocation, direct gets, counts, and deterministic bounded lists support later service/CLI work without relaxing lifecycle guarantees.

The repository boundary is append-only; no cross-dialect trigger is claimed. Concurrent sequence allocation must still handle the unique constraint as the authoritative race guard. SQLite two-session coverage verifies insertion-versus-completion serialization; PostgreSQL remains an integration-test gap.

## Canonical provenance types

`SpotScoringConfiguration` and `SurferProfileSnapshot` are frozen validated values. Their canonical payloads are persisted beside SHA-256 hashes derived by the repository; caller-supplied opaque hashes are not accepted. The validated profile name is persisted separately. Engine/profile versions and profile names are excluded from behavior hashes. Booleans are not accepted as numbers; non-finite numbers, unordered or incomplete bounds, values outside the storage `0..100` domain, invalid versions, unknown profiles, and signed-zero hash differences fail closed.

The profile snapshots preserve only the directly evidenced physical wave/period ranges from the application's existing selectable proficiency categories. Legacy hazard penalties and advanced-fit points are intentionally omitted: converting them into normalized tolerances or new deductions would invent product semantics. Hazard handling, technical-spot behavior, factor weights, missing-data policy, classification thresholds, and `safety_score` semantics remain explicit product gates. This slice does not define how any profile field contributes to a score.

## Migration and legacy data

Migration `0008_spot_scoring_foundation` converts existing score runs into explicit legacy provenance envelopes with recalculation sequence `0` and a canonical scope derived from the assessment points belonging to their input run.

Existing score snapshots are backfilled only when their unique score-run assessment input plus spot/time identity resolves to an assessment point. Legacy run hashes are re-derived from explicit legacy payload envelopes, the profile is named `legacy-unknown`, and scope is reconstructed from the complete assessment-point set. Upgrade preflights provenance, version narrowing, every new score/penalty range, and completed-run exact coverage before the first batch DDL. Each failure is repair-and-retry safe without manual Alembic artifact cleanup.

Downgrade to `0007` is **data-dependent** after multiple scopes or recalculation attempts exist: `0007`'s narrower uniqueness cannot represent those rows. A collision preflight runs before downgrade batch DDL and supports repair then retry without temporary-table cleanup. Operators must retain `0008` or explicitly resolve duplicate score-run identities before downgrade. Dropping canonical payloads and `assessment_point_id` loses stronger provenance and must be treated as an intentional rollback.

## Database defenses

The migration adds:

- nonnegative recalculation-sequence check;
- input + scope + sequence uniqueness and 80-character engine/profile version parity;
- run status/input/equivalence indexes;
- restrictive typed assessment-point foreign key and per-run point uniqueness;
- per-component, total-score, and penalty `0..100` checks;
- run, assessment-point, and spot/time snapshot indexes.

No total score formula or scoring policy is present.
