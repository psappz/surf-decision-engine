# Consensus input selection

For every spot, exact `valid_at`, provider and field, selection is deterministic and historical-cutoff safe.

## Availability cutoff

A run/point is eligible only when all four knowledge timestamps are non-null and at or before `forecast_cutoff_at`:

- `ForecastRun.issued_at`
- `ForecastRun.fetched_at`
- `ForecastRun.normalized_at`
- `ProviderForecastPoint.created_at`

Equality with the cutoff is eligible. A legacy null timestamp is conservatively treated as unavailable, because the engine cannot prove that the value was known at the historical cutoff.

## Run and sample selection

The latest eligible run is selected per spot, provider and exact `valid_at`. Within that run, sample selection happens separately per field:

1. validate the field value;
2. apply maximum source/model age, provider-field weight, quality, freshness and spatial eligibility;
3. choose the highest spatial-relevance sample;
4. use actual distance and stable sample/point identity as deterministic tie-breakers.

This preserves field coverage when one provider sample contains wave height while another contains period. One provider contributes at most once per field, and multiple samples never satisfy a multi-provider minimum.

Consensus v1 performs no interpolation and records `interpolation_method=exact_valid_at_only`.

## Exclusions

Bounded provenance is retained for missing, nonnumeric, nonfinite, negative, maximum-age, zero-weight/IPMA, quality-excluded, freshness-zero, spatial-zero and non-selected sample inputs. Excluded inputs always have zero effective weight and cannot affect the consensus value.
