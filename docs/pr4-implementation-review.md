# PR #4 implementation review

Spot Intelligence now consumes exactly one completed immutable Consensus run and snapshots only output-relevant `SurfSpot` rule fields. Canonical SHA-256 hashes cover every behavioral global setting and the exact sorted rule rows, including spot IDs, invalid raw audit values, effective fallbacks, and metadata issues. Display/private/unrelated fields are excluded.

Repository lifecycle guards creation as running, point insertion into an existing running run, and one terminal running-to-completed/failed transition. Service transactions prevent partial points and bound/redact audit data. Idempotency reuses equivalent completed calculations by consensus run, rule hash, engine/config hashes, and exact point scope. Forced calculations create distinct immutable records. Migration `0007` replaces the old input-only uniqueness constraint with an input-plus-scope-plus-recalculation-sequence constraint. This preserves database enforcement for each ordinary sequence-zero scope while allowing explicit forced reruns. Downgrade is data-dependent after forced reruns because the older schema cannot represent them without collisions.

Factor outputs are independently reviewable and do not include a total score or recommendation semantics. The breaking transform is explicitly provisional/model-derived. Current runtime scoring, recommendation, provider, UI, template/static, and scheduler read paths are untouched.

Independent review should verify formulas against `docs/spot-intelligence.md`, inspect persisted provenance using the CLI, review migration upgrade/downgrade behavior, and confirm the protected-path diff against `develop` remains empty.
