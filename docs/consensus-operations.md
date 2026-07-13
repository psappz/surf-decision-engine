# Consensus operations

Disabled by default:

```bash
CONSENSUS_ENGINE_ENABLED=false
CONSENSUS_ENGINE_VERSION=consensus-v1
CONSENSUS_RECALCULATION_DEBOUNCE_SECONDS=120
```

Manual commands:

```bash
python -m app.tools.consensus calculate-latest
python -m app.tools.consensus calculate --cutoff 2026-07-13T12:00:00Z --valid-from 2026-07-13T12:00:00Z --valid-until 2026-07-16T12:00:00Z
python -m app.tools.consensus status
python -m app.tools.consensus inspect-run <run-id>
python -m app.tools.consensus explain-point <point-id>
```

Commands print bounded JSON without credentials. Use `--dry-run` to estimate points without writing and `--force` only for explicit recalculation.
