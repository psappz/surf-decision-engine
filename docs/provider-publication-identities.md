# Provider publication identities

Publication identities are deterministic and never use `fetched_at` as the sole identity.

## Copernicus Marine
Inputs: provider, product ID, dataset ID, model cycle, latest valid forecast timestamp, and catalogue metadata fingerprint. Format: `copernicus:<product>:<dataset>:<cycle>:<latest-or-fingerprint>`.

## Open-Meteo Marine
Inputs: provider name, request geography, temporal range, issue/update metadata when exposed, otherwise bounded content hash. Weather and marine are separate providers and produce distinct identities.

## Open-Meteo Weather
Same strategy as marine, but provider/product identity is `open-meteo-weather` so wind/weather runs never collide with marine wave runs.

## IPMA
Inputs: feed type, endpoint identity, `dataUpdate`, `forecastDate`, location id such as Sagres `1081526`, and category. Daily range feeds are not expanded into fake hourly identities.
