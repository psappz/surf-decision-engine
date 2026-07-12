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
docker logs wavewatch-app
docker logs wavewatch-worker
```

## Retention

- Successful raw NetCDF files: latest 4 completed publications.
- Failed/incomplete temporary files: retained up to 7 days.
- Normalized DB data: retained unless a future app-level retention policy says otherwise.

Never delete the raw file for the currently active successful publication.
