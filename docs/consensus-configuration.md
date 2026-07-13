# Consensus configuration

Default engine version: `consensus-v1`.

Functional configuration is serialized canonically with sorted dictionary keys and stable float formatting, then SHA-256 hashed. Display labels and comments are excluded from the hash. Secrets are not configuration inputs.

Configurable fields include provider weights by field, maximum provider age, maximum issue-time age, source/model/horizon linear decay, minimum providers per field, field agreement thresholds, outlier policy, direction-vector minimum magnitude, missing-value rules, field fallbacks, IPMA corroboration policy, quality flag adjustments, spatial relevance and confidence-input weights.

All functional fields affect `configuration_hash`. Units are hours for age/horizon decay, minutes for time tolerance, kilometres for spatial relevance, 0–1 for factors/weights, and 0–100 for stored quality scores.
