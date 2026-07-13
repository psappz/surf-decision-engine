# Production deployment

Production URL: `https://loli.restricted.invalid`.

Production path: `/opt/wavewatch/app`.

Surf Decision Engine runs behind the shared `smartfinca-caddy` reverse proxy. Do not alter DNS, do not alter unrelated Caddy routes, and do not expose new public ports.

## Standard deployment checklist

1. Create a feature branch.
2. Inspect the current production database and containers.
3. Back up `/opt/wavewatch/app` configuration/source.
4. Back up the PostgreSQL database with `pg_dump`.
5. Back up or verify the media volume.
6. Run local tests.
7. Sync application source excluding `.env`, `.venv`, `.git`, local DB files and caches.
8. Rebuild with `docker compose -f docker-compose.prod.yml build` or `up -d --build`.
9. Apply Alembic migrations safely.
10. Confirm `surf-decision-engine-app`, `surf-decision-engine-worker`, and `surf-decision-engine-db` are running.
11. Run production smoke checks: `/health`, login, `/surf`, `/adm`, `/mod`, photo upload, webcam suggestion and approval.
12. Preserve Copernicus jobs/provider integrations and `/etc/cron.d/wavewatch-copernicus`.

Copernicus secrets stay outside the app repo at `/opt/wavewatch/secrets/copernicus.env` with mode `0600`.

## Media volume

User-uploaded spot photos are stored outside the ephemeral app container filesystem.

Production compose mounts:

```text
wavewatch_media:/data/media
```

The application environment sets:

```text
MEDIA_ROOT=/data/media
MAX_UPLOAD_FILES=10
MAX_UPLOAD_FILE_MB=15
MAX_UPLOAD_TOTAL_MB=60
```

The `wavewatch_media` Docker volume must be included in backup coverage. Media paths stored in PostgreSQL are relative to `MEDIA_ROOT`; images are not stored in PostgreSQL.

## Body-size configuration

The local app Caddyfile and production reverse-proxy route should allow at least the configured total upload limit:

```caddy
request_body {
  max_size 60MB
}
```

Do not lower the proxy limit below `MAX_UPLOAD_TOTAL_MB`, or valid uploads will fail before reaching the application.

## Migrations

The spot administration/media feature adds:

- `spot_webcams`
- `webcam_suggestions`
- `spot_photos`

Existing users and surf spots are preserved. Deprecated generic webcam fields are left unused for compatibility; generic aggregator links are not migrated into approved webcam records.

## Rollback

- Restore the latest app tarball backup into `/opt/wavewatch/app`.
- Restore the matching DB dump if schema/data rollback is required.
- Restore compose/Caddy configuration backups.
- Rebuild/restart with the previous compose files.
- Preserve or restore `wavewatch_media` depending on whether uploaded photos must remain available after rollback.
- Remove or disable `/etc/cron.d/wavewatch-copernicus` only when rolling back Copernicus scheduling itself.

## PR 2 provider ledger dual-write note

Surf Decision Engine provider ingestion can dual-write successful provider runs into the append-only Forecast Ledger when `PROVIDER_LEDGER_WRITES_ENABLED=true`. The default remains disabled for production-style environments. Current runtime tables, recommendations, scoring, scheduler ownership, and UI read paths remain unchanged. See `docs/provider-ledger-writes.md`, `docs/provider-data-mapping.md`, and `docs/provider-ledger-failure-recovery.md` for the PR 2 implementation details.
