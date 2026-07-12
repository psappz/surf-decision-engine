from dataclasses import dataclass
from datetime import datetime, UTC
import httpx, math
@dataclass
class MarineForecastPoint:
    timestamp: datetime; values: dict; provider: str
class MarineForecastProvider:
    name='base'
    async def fetch_forecast(self, latitude:float, longitude:float, start:datetime, end:datetime)->list[MarineForecastPoint]: raise NotImplementedError
class OpenMeteoMarineProvider(MarineForecastProvider):
    name='open-meteo-marine'
    async def fetch_forecast(self, latitude, longitude, start, end):
        params={'latitude':latitude,'longitude':longitude,'hourly':'wave_height,wave_direction,wave_period,swell_wave_height,swell_wave_direction,swell_wave_period,wind_wave_height,wind_wave_direction,wind_wave_period,sea_surface_temperature,ocean_current_velocity,ocean_current_direction','start_date':start.date().isoformat(),'end_date':end.date().isoformat(),'timezone':'UTC'}
        async with httpx.AsyncClient(timeout=10) as client:
            r=await client.get('https://marine-api.open-meteo.com/v1/marine', params=params); r.raise_for_status(); data=r.json()
        h=data.get('hourly',{}); out=[]
        for i,t in enumerate(h.get('time',[])):
            ts=datetime.fromisoformat(t).replace(tzinfo=UTC); vals={k:v[i] for k,v in h.items() if k!='time' and isinstance(v,list) and i < len(v)}
            out.append(MarineForecastPoint(ts, vals, self.name))
        return out
class OpenMeteoWeatherProvider(MarineForecastProvider):
    name='open-meteo-weather'
    async def fetch_forecast(self, latitude, longitude, start, end):
        params={'latitude':latitude,'longitude':longitude,'hourly':'wind_speed_10m,wind_direction_10m,wind_gusts_10m,temperature_2m,precipitation,cloud_cover,visibility','start_date':start.date().isoformat(),'end_date':end.date().isoformat(),'timezone':'UTC'}
        async with httpx.AsyncClient(timeout=10) as client:
            r=await client.get('https://api.open-meteo.com/v1/forecast', params=params); r.raise_for_status(); data=r.json()
        h=data.get('hourly',{}); return [MarineForecastPoint(datetime.fromisoformat(t).replace(tzinfo=UTC), {k:v[i] for k,v in h.items() if k!='time' and isinstance(v,list) and i<len(v)}, self.name) for i,t in enumerate(h.get('time',[]))]
class IPMAProvider(MarineForecastProvider):
    name='ipma-open-data'
    async def fetch_forecast(self, latitude, longitude, start, end):
        # Regional corroboration shell. Exact point marine feed is not assumed.
        return []
class CopernicusMarineProvider(MarineForecastProvider):
    name='copernicus-marine-disabled'
    enabled=False
    async def fetch_forecast(self, latitude, longitude, start, end): return []
class TideProvider(MarineForecastProvider):
    name='astronomical-tide-estimate'
    async def fetch_forecast(self, latitude, longitude, start, end):
        pts=[]; hours=int((end-start).total_seconds()//3600)+1
        for n in range(hours):
            ts=start.replace(minute=0,second=0,microsecond=0)+__import__('datetime').timedelta(hours=n)
            phase=(ts.timestamp()/3600)%12.42/12.42; level=(math.sin(phase*2*math.pi)+1)/2
            rising=math.cos(phase*2*math.pi)>0
            pts.append(MarineForecastPoint(ts, {'water_level':round(level,2),'state':'rising' if rising else 'falling','estimated':True,'time_to_next_high_hours':round(((0.25-phase)%1)*12.42,1),'time_to_next_low_hours':round(((0.75-phase)%1)*12.42,1),'tidal_change_rate':round(abs(math.cos(phase*2*math.pi)),2)}, self.name))
        return pts
class BuoyObservationProvider:
    name='future-buoy-observations'
    async def fetch_observations(self): return []
