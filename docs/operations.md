# Operations

## Copernicus status

```bash
cd /opt/wavewatch/app
docker compose -f docker-compose.prod.yml exec -T app python -m app.tools.copernicus status
```

## Manual checks

```bash
docker compose -f docker-compose.prod.yml exec -T app python -m app.tools.copernicus verify-auth
docker compose -f docker-compose.prod.yml exec -T app python -m app.tools.copernicus inspect
docker compose -f docker-compose.prod.yml exec -T app python -m app.tools.copernicus check
docker compose -f docker-compose.prod.yml exec -T app python -m app.tools.copernicus reconcile
```

## Manual recovery

Queue/import the latest publication idempotently:

```bash
docker compose -f docker-compose.prod.yml exec -T app python -m app.tools.copernicus enqueue-latest
docker compose -f docker-compose.prod.yml exec -T worker python -m app.workers.copernicus
```

Force one idempotent ingestion attempt:

```bash
docker compose -f docker-compose.prod.yml exec -T worker python -m app.tools.copernicus ingest-latest
```

## Logs

Cron log:

```text
/var/log/wavewatch/copernicus-cron.log
```

Application logs:

```bash
docker logs surf-decision-engine-app
docker logs surf-decision-engine-worker
```

## Retention

- Successful raw NetCDF files: latest 4 completed publications.
- Failed/incomplete temporary files: retained up to 7 days.
- Normalized DB data: retained unless a future app-level retention policy says otherwise.

Never delete the raw file for the currently active successful publication.

## PR 2 provider ledger dual-write note

Surf Decision Engine provider ingestion can dual-write successful provider runs into the append-only Forecast Ledger when `PROVIDER_LEDGER_WRITES_ENABLED=true`. The default remains disabled for production-style environments. Current runtime tables, recommendations, scoring, scheduler ownership, and UI read paths remain unchanged. See `docs/provider-ledger-writes.md`, `docs/provider-data-mapping.md`, and `docs/provider-ledger-failure-recovery.md` for the PR 2 implementation details.
