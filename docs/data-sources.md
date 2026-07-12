# Data sources

## Open-Meteo Marine API
Adapter: `OpenMeteoMarineProvider`. It requests hourly wave height/direction/period, swell wave height/direction/period, wind-wave fields, sea-surface temperature, and current fields from the free Open-Meteo Marine endpoint. It is replaceable because licensing may differ for later commercial use. Provider refreshes are protected by a 30-minute bundle limit: all HTTP calls required for one provider refresh count as one bundle.

## Open-Meteo Weather API
Adapter: `OpenMeteoWeatherProvider`. It requests wind speed/direction/gusts, air temperature, precipitation, cloud cover, and visibility.

## IPMA Open Data
Adapter shell: `IPMAProvider`. It is marked degraded because no precise spot-level marine endpoint has been selected for this local prototype without relying on unstable scraping. It should be used as regional corroboration when implemented.

## Copernicus Marine
Adapter: `CopernicusMarineProvider`. Product candidate: `GLOBAL_ANALYSISFORECAST_WAV_001_027`; selected forecast dataset id: `cmems_mod_glo_wav_anfc_0.083deg_PT3H-i`. The companion `cmems_mod_wav_anfc_0.083deg_static` dataset is static metadata/bathymetry-style support data, not the time-varying forecast feed for scoring. The provider is disabled until the Copernicus Marine Toolbox, non-interactive credentials, the verified forecast `COPERNICUSMARINE_DATASET_ID`, and a verified `COPERNICUSMARINE_VARIABLE_MAP_JSON` are configured. Do not fabricate dataset ids, variable names, or values. Implementation notes and the pending `describe` checklist are in `docs/copernicus-marine-integration.md`.

## Tide
The prototype uses an open astronomical estimate adapter and labels tide data as estimated. Replace with official Portuguese hydrographic data if a stable public endpoint is chosen.

## Buoys and webcams
Buoy observation and webcam confirmation boundaries exist for future use. The prototype does not scrape or run computer vision on third-party webcam pages.
