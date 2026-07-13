# Provider data mapping

## Copernicus Marine
| Native | Ledger field | Unit | Nullability | Transformation | Quality flag |
| --- | --- | --- | --- | --- | --- |
| VHM0 | wave_height | m | nullable | numeric copy | missing/masked |
| VMDR | wave_direction | degrees | nullable | numeric copy | missing/masked |
| VTPK | wave_period | s | nullable | numeric copy | missing/masked |
| VHM0_SW1 | swell_wave_height | m | nullable | numeric copy | missing |
| VMDR_SW1 | swell_wave_direction | degrees | nullable | numeric copy | missing |
| VTM01_SW1 | swell_wave_period | s | nullable | numeric copy | missing |
| VHM0_WW | wind_wave_height | m | nullable | numeric copy | missing |
| VMDR_WW | wind_wave_direction | degrees | nullable | numeric copy | missing |
| VTM01_WW | wind_wave_period | s | nullable | numeric copy | missing |

## Open-Meteo Marine
| Native | Ledger field | Unit | Transformation |
| --- | --- | --- | --- |
| wave_height | wave_height | m | copy |
| wave_direction | wave_direction | degrees | copy |
| wave_period | wave_period | s | copy |
| swell_wave_height | swell_wave_height | m | copy |
| swell_wave_direction | swell_wave_direction | degrees | copy |
| swell_wave_period | swell_wave_period | s | copy |
| wind_wave_height | wind_wave_height | m | copy |
| wind_wave_direction | wind_wave_direction | degrees | copy |
| wind_wave_period | wind_wave_period | s | copy |
| sea_surface_temperature | water_temperature | C | copy |
| ocean_current_velocity | current_speed | m/s | copy |
| ocean_current_direction | current_direction | degrees | copy |

## Open-Meteo Weather
| Native | Ledger field | Unit | Transformation |
| --- | --- | --- | --- |
| wind_speed_10m | wind_speed | km/h | copy |
| wind_direction_10m | wind_direction | degrees | copy |
| wind_gusts_10m | wind_gust | km/h | copy |
| temperature_2m, precipitation, cloud_cover, visibility | raw_values_json | provider-native | retained |

## IPMA
IPMA sea feeds contain daily ranges such as `waveHighMin`, `waveHighMax`, `wavePeriodMin`, `wavePeriodMax`, `predWaveDir`, `sstMin`, `sstMax`, `totalSeaMin`, `totalSeaMax`, `forecastDate`, and `dataUpdate`. PR 2 does not map daily ranges to fake hourly points.
