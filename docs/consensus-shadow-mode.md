# Consensus shadow mode

Shadow mode exists so provider-combined values can be accumulated, explained and compared before affecting surfers.

Current runtime source of truth remains the existing runtime forecast tables, score calculations, daypart logic and recommendations. PR #3 does not add user-facing UI and does not query consensus tables from `/surf` or spot detail pages.

A later read-path migration requires a validation period, Spot Intelligence, Recommendation and Confidence engines, and explicit product approval.
