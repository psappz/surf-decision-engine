# Consensus provider weights

Weights are field-specific, not global provider rankings.

Copernicus Marine has weight 1.0 for total wave, swell and wind-wave fields and zero wind weight because it is the strongest current offshore wave source here.

Open-Meteo Marine has secondary marine weights: 0.75 total wave height/direction, 0.70 period/swell, 0.65 wind-wave/swell period, 0.80 water temperature and 0.70 currents.

Open-Meteo Weather has weight 1.0 for wind speed, wind direction and wind gust.

IPMA has direct hourly weight 0.0 for every field. This zero-weight configuration is the executable policy: IPMA is retained only as excluded provenance and is not averaged into exact hourly values. No separate unsupported corroboration setting is hashed.
