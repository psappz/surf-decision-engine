# Data sources

## Open-Meteo Marine API
Adapter: `OpenMeteoMarineProvider`. It requests hourly wave height/direction/period, swell wave height/direction/period, wind-wave fields, sea-surface temperature, and current fields from the free Open-Meteo Marine endpoint. It is replaceable because licensing may differ for later commercial use.

## Open-Meteo Weather API
Adapter: `OpenMeteoWeatherProvider`. It requests wind speed/direction/gusts, air temperature, precipitation, cloud cover, and visibility.

## IPMA Open Data
Adapter shell: `IPMAProvider`. It is marked degraded because no precise spot-level marine endpoint has been selected for this local prototype without relying on unstable scraping. It should be used as regional corroboration when implemented.

## Copernicus Marine
Adapter boundary exists and is disabled by default. Product candidate: `IBI_ANALYSISFORECAST_WAV_005_005`. Do not fabricate values; enable only with valid configuration and non-interactive runtime credentials.

## Tide
The prototype uses an open astronomical estimate adapter and labels tide data as estimated. Replace with official Portuguese hydrographic data if a stable public endpoint is chosen.

## Buoys and webcams
Buoy observation and webcam confirmation boundaries exist for future use. The prototype does not scrape or run computer vision on third-party webcam pages.
