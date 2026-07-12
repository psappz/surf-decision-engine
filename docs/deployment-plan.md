# Future deployment plan

Target: `loli.restricted.invalid`.

Future production rollout should:
1. Back up current VPS state.
2. Build Docker image.
3. Provision PostgreSQL volume and secrets.
4. Configure Caddy virtual host and TLS.
5. Run Alembic migrations.
6. Seed only idempotent base data.
7. Smoke-test `/health`, `/login`, `/surf`, and spot pages.
8. Verify cookies are `Secure` under HTTPS.

This task intentionally did not connect to the VPS, deploy containers, change DNS, change Caddy, or alter firewall/server configuration.
