# Consensus operations

Disabled by default:

```bash
CONSENSUS_ENGINE_ENABLED=false
CONSENSUS_ENGINE_VERSION=consensus-v1
CONSENSUS_RECALCULATION_DEBOUNCE_SECONDS=120
```

Manual commands:

```bash
python -m app.tools.consensus calculate-latest [--hours 72] [--dry-run] [--force]
python -m app.tools.consensus calculate --cutoff 2026-07-13T12:00:00Z --valid-from 2026-07-13T12:00:00Z --valid-until 2026-07-16T12:00:00Z [--dry-run] [--force]
python -m app.tools.consensus status [--limit 10]
python -m app.tools.consensus inspect-run <run-id> [--limit 50]
python -m app.tools.consensus explain-point <point-id>
```

The CLI rejects negative horizons, nonpositive IDs, malformed timestamps and inverted valid ranges before opening a calculation run. Duplicate spot IDs are canonicalized.

`inspect-run` first resolves the run, so an existing failed or zero-point run is distinct from a nonexistent run. Inspection reports total/returned point counts and truncation. Missing run/point commands return code 2.

Commands print recursively bounded, secret-redacted JSON. `--dry-run` calculates without writing. `--force` appends a deliberate new run instead of reusing an equivalent completed one.
