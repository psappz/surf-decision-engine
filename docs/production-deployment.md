# Production deployment

Production URL: `https://loli.restricted.invalid`.

Production path: `/opt/wavewatch/app`.

WaveWatch runs behind the shared `smartfinca-caddy` reverse proxy. Do not alter DNS and do not expose new public ports.

Deployment steps:

1. Run local tests.
2. Back up `/opt/wavewatch/app` and `wavewatch-db`.
3. Sync application source excluding `.env`, `.venv`, `.git`, local DB files, caches, and upload data unless explicitly migrating uploads.
4. Store Copernicus secrets outside the app repo at `/opt/wavewatch/secrets/copernicus.env` with mode `0600`.
5. Rebuild with `docker compose -f docker-compose.prod.yml up -d --build`.
6. Confirm `wavewatch-app`, `wavewatch-worker`, and `wavewatch-db` are running.
7. Run `python -m app.tools.copernicus status` inside the app container.
8. Install `/etc/cron.d/wavewatch-copernicus`.
9. Smoke `https://loli.restricted.invalid/health`, login, `/surf`, and `/adm`.

Rollback:

- restore the latest app tarball backup into `/opt/wavewatch/app`;
- restore the matching DB dump if schema/data rollback is required;
- rebuild/restart with the previous compose files;
- remove or disable `/etc/cron.d/wavewatch-copernicus` if rolling back Copernicus scheduling.
