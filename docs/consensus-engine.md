# Consensus Engine

The Consensus Engine turns immutable provider Forecast Ledger points into versioned, append-only provider-combined forecast points for each surf spot and forecast timestamp.

```text
External providers → Provider Engine → Forecast Ledger
Forecast Ledger → Consensus Engine → consensus_runs → consensus_forecast_points
```

It answers: what is the best provider-combined offshore/weather estimate for this spot and timestamp? It does not transform offshore conditions at a beach, choose a surf spot, or produce final confidence. Those belong to later Spot Intelligence, Recommendation and Confidence engines.

Each non-dry calculation creates or reuses a `consensus_run` identified by engine version, configuration hash, forecast cutoff, scope and selected provider input fingerprint. Dry runs always calculate a fresh preview and write nothing. Points and terminal run records are treated as append-only by the consensus repository/service boundary, so newer results do not overwrite older results through supported application code.

This append-only policy is application-boundary enforcement, not database-wide immutability: this change adds no database triggers and does not prevent privileged arbitrary direct SQL from modifying rows.

Consensus v1 is shadow-only: current `/surf` and `/surf/spots/{slug}` pages continue to read runtime tables and existing recommendation output.
