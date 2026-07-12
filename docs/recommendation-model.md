# Recommendation model

The engine is deterministic and rule-based. For every spot and daypart it scores all hourly points, uses a median-like aggregate, penalizes volatility, and selects the best current recommendation.

Components: swell direction fit 0–20, swell height 0–15, swell period 0–15, wind direction 0–15, wind speed 0–10, tide 0–10, exposure 0–5, advanced-surfer fit 0–5, source agreement 0–3, freshness 0–2.

Penalties include unsafe wave height, strong onshore wind, extreme wind, stale data, missing core parameters, low base confidence, river-mouth complexity, reef/rock hazards, and high volatility.

Breaking-wave range is provisional: offshore swell is adjusted by exposure factor, shelter factor, direction fit, period energy, and tide adjustment. The UI labels it `Estimated breaking-wave range` and rounds to practical ranges.

Confidence is separate from quality: high score plus low confidence remains possible. `Live confirmed` is reserved for future direct observation, licensed webcam analysis, or user reports.
