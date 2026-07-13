# Consensus configuration

Default engine version: `consensus-v1`.

Functional configuration is serialized canonically with sorted dictionary keys and stable float formatting, then SHA-256 hashed. Display labels are excluded. Secrets are not configuration inputs. A request whose engine version differs from its configuration is rejected before any run is written.

## Supported hashed semantics

- provider weights by provider and normalized field;
- hard maximum provider-fetch age and model-issue age;
- source-age, model-cycle-age and forecast-horizon decay;
- distinct minimum providers per field;
- scalar agreement and outlier thresholds;
- outlier mode, factor and distinct-provider threshold;
- configured direction fields and minimum resultant-vector magnitude;
- unique known expected fields used for completeness;
- quality-flag factors;
- spatial distance thresholds and unknown-coordinate factor;
- confidence-input component weights.

Previously declared but unsupported `required_fields`, `optional_fields`, `missing_value_rules`, `field_specific_fallback_behavior` and redundant IPMA policy settings were removed from executable hashed configuration. IPMA direct hourly behavior is represented by zero field weights.

## Validation

Configuration validation rejects:

- unknown or duplicate direction/expected fields;
- empty expected fields;
- negative, nonfinite or malformed weights/ages/decays;
- unsupported outlier modes;
- invalid spatial thresholds;
- confidence weights that do not sum to one.

Units are hours for ages/decays, kilometres for spatial relevance, 0–1 for factors/weights, and 0–100 for persisted scores. Completeness and confidence-input scores are defensively clamped to 0–100.
