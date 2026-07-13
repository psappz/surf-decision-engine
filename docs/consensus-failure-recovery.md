# Consensus failure recovery

Run statuses are `running`, `completed` and `failed`. The preferred v1 behavior is one transactional batch per requested scope. A run is completed only after point inserts succeed.

Safe retry: rerun the same command without `--force`; an equivalent completed input fingerprint is reused. If a run failed before completion, rerun after fixing the cause. Use forced recalculation only when a deliberate new append-only run is wanted.

A stale `running` state after process death should be inspected through `status` and database metadata before retry. Configuration changes create a different hash and therefore a different run lineage.
