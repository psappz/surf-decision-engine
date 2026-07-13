# Copernicus Marine integration

Target product candidate: `GLOBAL_ANALYSISFORECAST_WAV_001_027`.

Important: `GLOBAL_ANALYSISFORECAST_WAV_001_027` is a Copernicus Marine product id candidate, not yet a verified toolbox dataset id. The toolbox `subset --dataset-id ...` command requires a concrete dataset id exposed under the product. If it is passed the product id directly, the toolbox can return `Dataset not found`.

## Current state

Surf Decision Engine has a guarded Copernicus provider path, but it remains disabled until the toolbox, credentials, and verified dataset variable mapping are present. The app must not fetch Copernicus data during normal page rendering. Fetching happens only inside the protected provider refresh bundle.

## Required local/VPS environment

Do not commit these values.

```env
COPERNICUSMARINE_ENABLED=true
COPERNICUSMARINE_USERNAME=<set locally or on VPS>
COPERNICUSMARINE_PASSWORD=<set locally or on VPS>
COPERNICUSMARINE_DATASET_ID=cmems_mod_glo_wav_anfc_0.083deg_PT3H-i
COPERNICUSMARINE_CACHE_DIR=data/provider-cache/copernicus
COPERNICUSMARINE_VARIABLE_MAP_JSON={"wave_height":"<describe-var>","wave_direction":"<describe-var>","wave_period":"<describe-var>"}
```

`COPERNICUSMARINE_VARIABLE_MAP_JSON` must be filled from real toolbox `describe` output. Do not guess variable names.

## Toolbox commands

Install in the project virtualenv when external package access is allowed:

```bash
.venv/bin/pip install copernicusmarine xarray netCDF4
```

Then inspect the product variables:

```bash
.venv/bin/copernicusmarine describe \
  --product-id GLOBAL_ANALYSISFORECAST_WAV_001_027 \
  --return-fields all
```

Use the variable short names from that output for `COPERNICUSMARINE_VARIABLE_MAP_JSON`. The selected forecast dataset id is `cmems_mod_glo_wav_anfc_0.083deg_PT3H-i`.

Copernicus UI code samples may show a Python API call like:

```python
copernicusmarine.open_dataset(
    dataset_id="cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m",
    variables=["uo", "vo"],
    minimum_longitude=5.0,
    maximum_longitude=10.0,
    minimum_latitude=38.0,
    maximum_latitude=42.0,
)
```

Treat that only as proof of the API shape unless it is the selected wave product. `cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m` is a physical-current dataset sample using current variables `uo`/`vo`, and the shown bbox is not the Aljezur coast. Surf Decision Engine needs a wave forecast dataset and wave variables, not a current dataset.

Document the exact variable names for at least:

| Surf Decision Engine normalized field | Copernicus variable from `describe` | Status |
| --- | --- | --- |
| `wave_height` | `VHM0` | required; sea_surface_wave_significant_height |
| `wave_direction` | `VMDR` | required; sea_surface_wave_from_direction |
| `wave_period` | `VTPK` | required; sea_surface_wave_period_at_variance_spectral_density_maximum |
| `swell_wave_height` | `VHM0_SW1` | optional; primary swell significant height |
| `swell_wave_direction` | `VMDR_SW1` | optional; primary swell from direction |
| `swell_wave_period` | `VTM01_SW1` | optional; primary swell mean period |
| `wind_wave_height` | `VHM0_WW` | optional; wind wave significant height |
| `wind_wave_direction` | `VMDR_WW` | optional; wind wave from direction |
| `wind_wave_period` | `VTM01_WW` | optional; wind wave mean period |

## Minimal Aljezur subset test

The app builds one bounding-box subset command for all Aljezur surf spots. Example shape after variable mapping is verified:

```bash
copernicusmarine subset \
  --dataset-id <concrete dataset id from describe> \
  --minimum-longitude <min_lon> \
  --maximum-longitude <max_lon> \
  --minimum-latitude <min_lat> \
  --maximum-latitude <max_lat> \
  --start-datetime <utc-start> \
  --end-datetime <utc-end> \
  --variable <verified_wave_height_var> \
  --variable <verified_wave_direction_var> \
  --variable <verified_wave_period_var> \
  --output-directory data/provider-cache/copernicus \
  --output-filename wavewatch-copernicus-latest.nc \
  --force-download
```

The username/password are passed via environment, not command arguments, so they do not appear in process logs.

## Runtime behavior

- Missing toolbox, credentials, or variable map → provider status `disabled`; no external fetch attempted.
- Configured provider → one subset per protected refresh bundle, not per spot and not per page view.
- Download or parsing failure → `degraded`; existing recommendations remain available.
- Parsed values are stored in `marine_forecasts` with `provider_name='copernicus-marine'`.
- When Copernicus and mock/Open-Meteo-compatible marine values share the same forecast timestamp, scoring prefers Copernicus values.

## Verification before deploy

```bash
.venv/bin/pytest tests/test_copernicus.py tests/test_app.py -q
.venv/bin/pytest -q
```

Then run an authenticated smoke test and confirm provider status does not expose credentials.
