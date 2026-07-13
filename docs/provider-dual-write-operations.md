# Provider dual-write operations

## Enable locally
```bash
PROVIDER_LEDGER_WRITES_ENABLED=true DATABASE_URL=sqlite:///./wavewatch.db .venv/bin/pytest tests/test_provider_ledger_writer.py -q
```

## Disable
```bash
PROVIDER_LEDGER_WRITES_ENABLED=false
```

## Inspect publications
```sql
SELECT * FROM provider_publications ORDER BY detected_at DESC LIMIT 20;
```

## Inspect fetch attempts
```sql
SELECT * FROM provider_fetches WHERE publication_id = :publication_id ORDER BY attempt_number;
```

## Inspect runs and points
```sql
SELECT * FROM forecast_runs ORDER BY created_at DESC LIMIT 20;
SELECT COUNT(*) FROM provider_forecast_points WHERE forecast_run_id = :run_id;
```

## Detect partial success
```sql
SELECT id, provider_name, status, error_code, error_message FROM provider_fetches WHERE status = 'ledger_failed';
```

## Retry
Retry the provider job normally after fixing the cause. Existing successful ledger runs are not overwritten.

## Rollback
Disable `PROVIDER_LEDGER_WRITES_ENABLED`; current runtime read paths continue to work.
