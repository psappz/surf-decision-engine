# Consensus Engine

The Consensus Engine turns immutable provider Forecast Ledger points into versioned, append-only provider-combined forecast points for each surf spot and forecast timestamp.

```text
External providers → Provider Engine → Forecast Ledger
Forecast Ledger → Consensus Engine → consensus_runs → consensus_forecast_points
```

It answers: what is the best provider-combined offshore/weather estimate for this spot and timestamp? It does not transform offshore conditions at a beach, choose a surf spot, or produce final confidence. Those belong to later Spot Intelligence, Recommendation and Confidence engines.

Each calculation creates or reuses a `consensus_run` identified by engine version, configuration hash, forecast cutoff, scope and selected provider input fingerprint. Points are immutable rows under that run. Older consensus results are never overwritten.

Consensus v1 is shadow-only: current `/surf` and `/surf/spots/{slug}` pages continue to read runtime tables and existing recommendation output.
