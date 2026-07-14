# Spot Intelligence Engine (shadow mode)

PR #4 implements a deterministic, versioned assessment stage between Consensus and later Recommendation/Confidence work. Run it manually:

```bash
python -m app.tools.spot_intelligence calculate --consensus-run-id 42 [--spot-id 1] [--force] [--dry-run]
python -m app.tools.spot_intelligence status --limit 25 [--offset 0]
python -m app.tools.spot_intelligence inspect-run 7 --limit 50 [--offset 0]
python -m app.tools.spot_intelligence explain-point 99
```

IDs must be positive and offsets nonnegative. Status and inspect pages are capped at 100 and return totals, returned counts, truncation state, and the next offset. JSON is deterministic, bounded, and secret-redacted. A dry run always calculates afresh and writes nothing. An equivalent completed run is reused unless forced; an equivalent running run returns `in_progress` instead of starting a duplicate calculation. A non-dry failure after input validation leaves one failed, redacted audit run and no partial points. Retry normally after correcting the cause; the retry receives a new immutable attempt sequence. Use `--force` only to preserve a distinct rerun of already successful identical inputs. Concurrent allocation uses the database uniqueness constraint plus bounded retry; callers may retry after exceptional sustained contention.

`SPOT_INTELLIGENCE_ENGINE_VERSION` changes the explicit engine version. `SPOT_INTELLIGENCE_ENABLED` is visibility/configuration only: there is no automatic invocation, regardless of its value. The default is false.

## Deterministic formulas

All fit outputs are clamped to 0–100 or null when input/rules do not permit calculation.

- Circular swell direction: preferred arc = 100; acceptable arc = a deterministic partial fit tapering from the configured acceptable fit near preferred boundaries; outside = configured poor fit. Arcs support north-crossing wraparound.
- Height, period, and tide: 100 inside the ordered preferred range, linearly tapered outside over one configured range width, then 0. Height above the spot maximum is 0 and raises a structured hazard.
- Wind direction: 100 in the preferred circular arc, otherwise 0; null when input/rule is missing.
- Wind speed: 100 through the global safe threshold (10), linear to 0 at the global zero-fit threshold (25), then 0. Provenance explicitly states that no per-spot wind-speed fields exist.
- Exposure and shelter are clamped multiplicative transformations (default bounds 0.5–1.5), not duplicated score components. Missing/invalid values use neutral 1.0 with uncertainty.
- Provisional breaking face = best available nonnegative swell height (total-wave fallback allowed) × direction multiplier (0.65–1.0) × period multiplier (1.0–1.24) × bounded exposure × bounded shelter × tide multiplier (0.9–1.0). Bounds are face × 0.8 and face × 1.25, rounded to 0.1 m, nonnegative and ordered.

The engine emits structured hazards, uncertainty factors, and detailed provenance including upstream point/run/version/configuration, exact rules snapshot/hash, formula version, canonical selected-point scope/hash, fallbacks, and warnings. Exact required run provenance has a hard size envelope: calculation is rejected before creating a successful run if the canonical rules snapshot and selected point IDs cannot fit, rather than silently truncating them. Malformed directions, negative physical inputs, or quality values outside 0–100 are explicit invalid-input uncertainty and are not converted into misleading fits. Consensus agreement, freshness, completeness, spatial relevance, and confidence-input values are uncertainty inputs only; this is **not final confidence**.

## Limitations and boundary

Every assessment and breaking-wave range is model-derived; ranges are provisional. There are no observations, webcam inference, provider changes, IPMA activation, ranking, total surf score, classification, go/no-go, daypart selection, recommendation, final confidence, UI/read-path migration, scheduler, or production deployment. Recommendation Engine, Confidence Engine, scientific calibration, and UI migration remain later work.
