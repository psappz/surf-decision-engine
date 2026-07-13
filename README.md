# Surf Decision Engine local prototype

Surf Decision Engine is a private FastAPI/Jinja2 surf recommendation prototype for advanced surfers around Aljezur, Portugal. The future public host is `loli.restricted.invalid`, but this task intentionally performs **no VPS deployment**.

## Architecture
- FastAPI backend with server-rendered Jinja2 HTML and minimal CSS.
- PostgreSQL in Docker Compose; SQLAlchemy 2.x ORM. Tests can use SQLite for isolation.
- Alembic migration `0001_initial` defines users, sessions, surf spots, provider fetches, marine/weather/tide forecasts, buoy observations, spot scores, and daily recommendations.
- Caddy reverse-proxies local HTTP on `http://localhost:8080`.
- Provider adapters normalize data behind `MarineForecastProvider`; Open-Meteo adapters are implemented, IPMA is intentionally disabled, Copernicus scheduled ingestion is enabled when credentials/configuration are present, and buoy/webcam integrations are disabled by default.

## Local startup
```bash
cp .env.example .env
docker compose up --build
```
Open `http://localhost:8080`.

## Environment variables
- `DATABASE_URL`: SQLAlchemy database URL. Docker points to PostgreSQL.
- `SECRET_KEY`: local application secret placeholder.
- `SECURE_COOKIES`: set `true` behind HTTPS; default `false` for local HTTP.
- `ENABLE_LIVE_FETCH`: reserved for provider refresh behavior.

## Database initialization
The container runs:
```bash
alembic upgrade head
python -m app.seed
```
Seeding is idempotent and does not overwrite modified surf spots or users on restart.

## Seed users
Initial development credentials are defined by the build prompt and seeded with bcrypt hashes only. Passwords are not stored in plaintext. Usernames are matched case-insensitively.

## Data providers
Operational in the local prototype: internal Open-Meteo-compatible fixture data, astronomical tide estimate, and the adapter code for Open-Meteo Marine/Weather. Provider failures are represented as `healthy`, `degraded`, `unavailable`, or `disabled`.

## Free-source limitations
IPMA is intentionally disabled for the current Aljezur-focused app because it does not add useful spot-level accuracy beyond broad fallback coverage. Reconsider only if the app expands to more Portuguese regions or a specific useful spot-level IPMA feed is selected. Webcam confirmation is future licensed integration only; the app does not scrape or analyze third-party cameras.

## Recommendation formula
See `docs/recommendation-model.md`. The score is rule-based, inspectable, and 0–100. It considers swell direction/height/period, wind direction/speed, tide, exposure, advanced-surfer fit, source agreement, freshness, and safety penalties.

## Confidence formula
Confidence is independent of quality and depends on provider count/agreement, age, completeness, spot complexity, base confidence, and observation availability. Initial labels are Well supported, Estimated, and Uncertain. Live confirmed is reserved for future direct observations.

## Inspect provider status
Use `/health` or the Provider Status section in `/surf` and spot detail pages. Each provider is protected by a 30-minute data-gathering bundle limit: the limit applies to the complete provider refresh bundle, not to each individual HTTP request inside that bundle. Hover over a provider chip to see why it is healthy/degraded/disabled/unavailable; click it to open a dismissible modal with human-readable fetched values.

## Language and proficiency preferences
Surf Decision Engine supports English, German, and Portuguese UI labels. Authenticated pages expose a top-right language selector and a proficiency selector with `beginner`, `rookie`, `intermediate`, `advanced`, and `pro`. The proficiency selection changes recommendation scoring, alternatives, spot-detail scores, and the surf-call column in the surf-spot table. Preferences are stored in local SameSite=Lax cookies.

## Run tests
```bash
pytest -q
```
Tests use mocked/provider-fixture data and do not require live internet access.

## Add a surf spot
Edit `app/seed_data.py`, add a dictionary to `SPOTS`, and set structured parameters in `DEFAULT_PARAMS` or per-spot overrides. Existing seeded records are not overwritten; update the database or add a migration for production changes.

## Add another data provider
Create an adapter implementing `MarineForecastProvider.fetch_forecast()`, normalize into `MarineForecastPoint`, persist provider fetch status/raw subset/errors, and include tests with mocked responses.

## Future VPS deployment
Future deployment can run Docker, Caddy, and PostgreSQL for `loli.restricted.invalid`. This repository includes `docs/deployment-plan.md`, but no remote action, DNS change, firewall change, or VPS deployment was performed.

## PR 2 provider ledger dual-write note

Surf Decision Engine provider ingestion can dual-write successful provider runs into the append-only Forecast Ledger when `PROVIDER_LEDGER_WRITES_ENABLED=true`. The default remains disabled for production-style environments. Current runtime tables, recommendations, scoring, scheduler ownership, and UI read paths remain unchanged. See `docs/provider-ledger-writes.md`, `docs/provider-data-mapping.md`, and `docs/provider-ledger-failure-recovery.md` for the PR 2 implementation details.


## Consensus Engine shadow mode

PR #3 adds a versioned, append-only Consensus Engine in shadow mode. It reads immutable Forecast Ledger provider points and writes `consensus_runs` / `consensus_forecast_points`; current UI, runtime forecasts and recommendations remain unchanged. See `docs/consensus-engine.md` and `docs/consensus-operations.md`.
