# Consensus statistics

Scalar fields use weighted aggregation. Values are validated, quality/freshness/spatial factors adjust weights, a weighted median supplies a robust center, and extreme outliers are downweighted in v1 rather than silently discarded.

Direction fields use weighted vector averaging:

```text
x = Σ(weight × cos(angle))
y = Σ(weight × sin(angle))
direction = atan2(y, x)
```

The resultant vector magnitude is the direction agreement signal. If it falls below the configured minimum, direction consensus is null and provenance records directional cancellation.

Freshness is `source_age_factor × model_cycle_factor × forecast_horizon_factor`, each a documented linear decay clamped to 0–1. Agreement, freshness, completeness and confidence-input scores are normalized to 0–100. `confidence_input_score` is only an input for a future Confidence Engine.
