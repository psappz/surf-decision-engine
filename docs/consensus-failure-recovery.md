# Consensus failure recovery

Run statuses are `running`, `completed` and `failed`.

For every non-dry calculation, the engine persists and commits a `running` attempt before point construction. Point construction/insertion and the terminal completion transition then run as one transaction. A build or insert failure rolls back every point and transitions the durable run to `failed` with a bounded `failure_stage`.

Repository APIs permit only:

```text
running -> completed
running -> failed
```

They reject non-running creation, arbitrary status values, terminal-run metadata/error mutation, and point insertion into absent or terminal runs.

Stored and CLI-rendered errors redact common credential assignments, bearer/API tokens, credential-bearing URLs, secret-keyed structures and configured secret environment values. Nested metadata/provenance is bounded by depth, collection size, string size and total serialized size while retaining truncation/omitted counts.

Safe retry: rerun the same command without `--force`; an equivalent completed fingerprint is reused. Failed attempts remain audit records under the repository/service append-only policy. Use `--force` only to append a deliberate new run. This policy has no database triggers and does not claim protection from arbitrary privileged direct SQL.

A stale `running` state after process death must be inspected before retry. Automatic stale-run recovery and concurrent queue-level deduplication remain future operational work.
