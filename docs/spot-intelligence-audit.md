# Spot Intelligence architecture and rules audit (PR #4)

## Evidence and boundary

Evidence-backed responsibilities are those in `engine-architecture.md`: consume a completed Consensus run and transform its offshore conditions into per-spot direction/height/period/wind/tide fits, exposure/shelter transformations, local breaking-wave estimates, hazards, and uncertainty. `SurfSpot` supplies the existing rule fields. The legacy `scoring.py` is evidence only for circular ranges and the shape of its breaking transform (height × direction × period × exposure × shelter × tide); its profile scoring, totals, classifications, penalties, dayparts, recommendations, and confidence labels are deliberately not reused.

The new engine is manual, append-only at the repository/service boundary, deterministic, and shadow-only. It reads only `ConsensusForecastPoint` rows belonging to one completed `ConsensusRun`. It does not read mutable marine/weather/tide tables and has no scheduler or runtime/UI hook.

## Provisional decisions

Breaking-wave bounds are **model-derived and provisional**, never observed or live. Multipliers and practical 0.1 m rounding are engineering defaults, not a scientifically validated nearshore model. Global wind speed thresholds are used because `SurfSpot` has no wind-speed rule fields; provenance identifies that fallback. Static hazard text is supporting context under `STATIC_SPOT_HAZARD`, not condition inference. A missing tide height remains missing; `tide_preference` is retained and produces explicit uncertainty because Consensus does not carry tide state.

Invalid or incomplete spot metadata is normalized to an explicit null/default, included in the immutable snapshot with issue codes, and propagated into hazards/uncertainty. No value is silently invented.

## Schema decision

Schema through `0006` contains all assessment outputs and version fields, but one concrete lifecycle defect required `0007`: the old run uniqueness constraint made `--force` impossible and did not model calculation scope explicitly. `0007` adds a deterministic scope hash and recalculation sequence, then replaces the old constraint with input-plus-scope-plus-sequence uniqueness. Sequence zero retains database protection for ordinary idempotent runs; positive sequences preserve explicit forced reruns. A non-unique equivalence index supports lookup. Downgrade is data-dependent once forced reruns exist because the older schema cannot represent duplicate equivalent inputs. Append-only is an application-boundary claim; no cross-dialect trigger is added.
