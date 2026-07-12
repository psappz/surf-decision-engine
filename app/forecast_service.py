from datetime import datetime, timedelta, UTC
from sqlalchemy import delete
from .models import SurfSpot, MarineForecast, WeatherForecast, TideForecast, ProviderFetch, SpotScore, DailyRecommendation
from .providers import TideProvider
from .scoring import local_day_windows, aggregate_daypart
async def ensure_seed_forecasts(db):
    spots=db.query(SurfSpot).all(); now=datetime.now(UTC).replace(minute=0,second=0,microsecond=0); start=now-timedelta(hours=2); end=now+timedelta(hours=36)
    if db.query(MarineForecast).filter(MarineForecast.forecast_time>=now).first(): return
    pf=ProviderFetch(provider_name='mock-open-meteo-fixture',fetched_at=now,latitude=None,longitude=None,status='healthy',raw_response={'fixture':'clean long-period north-west swell'},parsing_errors=None,data_age_seconds=0); db.add(pf); db.flush()
    tide_points=await TideProvider().fetch_forecast(0,0,start,end)
    for spot in spots:
        for i in range(int((end-start).total_seconds()//3600)+1):
            ts=start+timedelta(hours=i); hour=ts.hour
            marine={'wave_height':1.4+(0.2 if hour>15 else 0),'wave_direction':310,'wave_period':12,'swell_wave_height':1.3+(0.3 if spot.slug in ['arrifana','amado'] else 0),'swell_wave_direction':315,'swell_wave_period':13,'sea_surface_temperature':18.5}
            weather={'wind_speed_10m':8 if hour<12 else 14,'wind_direction_10m':105 if hour<12 else 285,'wind_gusts_10m':18,'temperature_2m':22,'precipitation':0,'cloud_cover':30,'visibility':20000}
            db.add(MarineForecast(provider_fetch_id=pf.id,provider_name='mock-open-meteo-marine',spot_id=spot.id,forecast_time=ts,fetched_at=now,values=marine,provider_status='healthy'))
            db.add(WeatherForecast(provider_fetch_id=pf.id,provider_name='mock-open-meteo-weather',spot_id=spot.id,forecast_time=ts,fetched_at=now,values=weather,provider_status='healthy'))
            tv=next((p.values for p in tide_points if p.timestamp==ts), {'water_level':.5,'state':'estimated'})
            db.add(TideForecast(provider_fetch_id=pf.id,provider_name='astronomical-tide-estimate',spot_id=spot.id,forecast_time=ts,fetched_at=now,values=tv,provider_status='healthy'))
    db.commit(); calculate_recommendations(db)
def calculate_recommendations(db, score_date=None):
    now=datetime.now(UTC); score_date=score_date or now.astimezone(__import__('zoneinfo').ZoneInfo('Europe/Lisbon')).date(); db.execute(delete(DailyRecommendation).where(DailyRecommendation.score_date==score_date)); db.execute(delete(SpotScore).where(SpotScore.score_date==score_date)); db.commit()
    windows=local_day_windows(score_date); spots=db.query(SurfSpot).all()
    for daypart,(start,end) in windows.items():
        scores=[]
        for spot in spots:
            if not spot.is_active_for_recommendations: continue
            m={x.forecast_time:x.values for x in db.query(MarineForecast).filter(MarineForecast.spot_id==spot.id,MarineForecast.forecast_time>=start,MarineForecast.forecast_time<end).all()}
            w={x.forecast_time:x.values for x in db.query(WeatherForecast).filter(WeatherForecast.spot_id==spot.id,WeatherForecast.forecast_time>=start,WeatherForecast.forecast_time<end).all()}
            t={x.forecast_time:x.values for x in db.query(TideForecast).filter(TideForecast.spot_id==spot.id,TideForecast.forecast_time>=start,TideForecast.forecast_time<end).all()}
            res=aggregate_daypart(spot, sorted(m.items()), w, t, daypart)
            if not res: continue
            ss=SpotScore(spot_id=spot.id,daypart=daypart,score_date=score_date,score=res['score'],confidence_label=res['confidence_label'],classification=res['classification'],explanation=res['explanation'],summary=res,created_at=now); db.add(ss); db.flush(); scores.append(ss)
        if scores:
            best=max(scores,key=lambda s:s.score); db.add(DailyRecommendation(score_date=score_date,daypart=daypart,spot_score_id=best.id,created_at=now))
    db.commit()
def provider_status(db):
    statuses={'open-meteo-marine':'healthy' if db.query(MarineForecast).first() else 'unavailable','open-meteo-weather':'healthy' if db.query(WeatherForecast).first() else 'unavailable','ipma-open-data':'degraded','copernicus-marine':'disabled','astronomical-tide-estimate':'healthy' if db.query(TideForecast).first() else 'unavailable','buoy-observations':'disabled','webcam-confirmation':'disabled'}
    return statuses
