# Consensus input selection

For each provider, spot, sample point and exact `valid_at`, the selector chooses the latest eligible ledger point whose forecast run was issued and fetched at or before `forecast_cutoff_at`.

This supports historical questions such as: what would Surf Decision Engine have calculated using only provider data available at 07:00 UTC?

Consensus v1 uses exact timestamp matching only and records `interpolation_method=exact`. Inputs outside the requested valid range or after the cutoff are excluded. Provider point provenance includes provider, publication, fetch, run, point, issue/fetch/valid timestamps, raw value, weights, freshness, quality, spatial factor, schema and normalizer metadata.
