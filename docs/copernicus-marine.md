# Copernicus Marine Surf Decision Engine integration

## Identifiers

Surf Decision Engine uses the Copernicus Marine wave product:

- Product ID: `GLOBAL_ANALYSISFORECAST_WAV_001_027`
- Dataset ID: `cmems_mod_glo_wav_anfc_0.083deg_PT3H-i`

The product ID is used only for catalogue inspection. The dataset ID is passed to `copernicusmarine subset`.

## Variable mapping

| Surf Decision Engine field | Copernicus variable |
| --- | --- |
| `wave_height` | `VHM0` |
| `wave_direction` | `VMDR` |
| `wave_period` | `VTPK` |
| `swell_wave_height` | `VHM0_SW1` |
| `swell_wave_direction` | `VMDR_SW1` |
| `swell_wave_period` | `VTM01_SW1` |
| `wind_wave_height` | `VHM0_WW` |
| `wind_wave_direction` | `VMDR_WW` |
| `wind_wave_period` | `VTM01_WW` |

Core required variables are `VHM0`, `VMDR`, and `VTPK`. If any core variable is absent during catalogue inspection or NetCDF validation, Surf Decision Engine marks Copernicus degraded/failed and preserves previous successful data.

## Bounds

Configured by environment:

```env
COPERNICUS_MIN_LONGITUDE=-9.15
COPERNICUS_MAX_LONGITUDE=-8.65
COPERNICUS_MIN_LATITUDE=36.95
COPERNICUS_MAX_LATITUDE=37.60
```

These bounds cover the configured Aljezur beaches plus offshore grid cells west of the coast.

## Credentials

Credentials are supplied via environment variables:

```env
COPERNICUSMARINE_USERNAME=<secret>
COPERNICUSMARINE_PASSWORD=<secret>
```

Production stores them outside the app repository in `/opt/wavewatch/secrets/copernicus.env` with mode `0600`. Do not commit or print this file.

## Commands

Run from the production compose directory:

```bash
docker compose -f docker-compose.prod.yml exec -T app python -m app.tools.copernicus verify-auth
docker compose -f docker-compose.prod.yml exec -T app python -m app.tools.copernicus inspect
docker compose -f docker-compose.prod.yml exec -T app python -m app.tools.copernicus check
docker compose -f docker-compose.prod.yml exec -T app python -m app.tools.copernicus reconcile
docker compose -f docker-compose.prod.yml exec -T app python -m app.tools.copernicus enqueue-latest
docker compose -f docker-compose.prod.yml exec -T worker python -m app.workers.copernicus
docker compose -f docker-compose.prod.yml exec -T worker python -m app.tools.copernicus ingest-latest
docker compose -f docker-compose.prod.yml exec -T app python -m app.tools.copernicus status
```

HTTP requests never call these commands and never download or parse NetCDF files.

## PR 2 provider ledger dual-write note

Surf Decision Engine provider ingestion can dual-write successful provider runs into the append-only Forecast Ledger when `PROVIDER_LEDGER_WRITES_ENABLED=true`. The default remains disabled for production-style environments. Current runtime tables, recommendations, scoring, scheduler ownership, and UI read paths remain unchanged. See `docs/provider-ledger-writes.md`, `docs/provider-data-mapping.md`, and `docs/provider-ledger-failure-recovery.md` for the PR 2 implementation details.
