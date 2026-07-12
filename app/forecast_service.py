from datetime import datetime, timedelta, UTC
from types import SimpleNamespace
from sqlalchemy import delete, desc
from .models import SurfSpot, MarineForecast, WeatherForecast, TideForecast, ProviderFetch, SpotScore, DailyRecommendation, CopernicusPublication, CopernicusIngestionJob
from .providers import TideProvider
from .copernicus import aljezur_bbox, load_copernicus_config, parse_copernicus_netcdf, run_subset_download
from .scoring import local_day_windows, aggregate_daypart, normalize_profile

PROVIDER_FETCH_INTERVAL = timedelta(minutes=30)


def _aware(dt):
    return dt if dt and dt.tzinfo else (dt.replace(tzinfo=UTC) if dt else None)


def provider_can_fetch(db, provider_name: str, now: datetime | None = None) -> tuple[bool, datetime | None]:
    """Limit a provider data-gathering bundle to one run per 30 minutes."""
    now = now or datetime.now(UTC)
    last = db.query(ProviderFetch).filter(ProviderFetch.provider_name == provider_name).order_by(desc(ProviderFetch.fetched_at)).first()
    if not last:
        return True, None
    fetched_at = _aware(last.fetched_at)
    if now - fetched_at >= PROVIDER_FETCH_INTERVAL:
        return True, fetched_at
    return False, fetched_at


def _latest_fetch(db, provider_name: str):
    return db.query(ProviderFetch).filter(ProviderFetch.provider_name == provider_name).order_by(desc(ProviderFetch.fetched_at)).first()


def _fmt_age(dt):
    dt = _aware(dt)
    if not dt:
        return 'never fetched'
    minutes = int((datetime.now(UTC) - dt).total_seconds() // 60)
    if minutes < 1:
        return 'just now'
    if minutes < 60:
        return f'{minutes} minutes ago'
    return f'{minutes//60} h {minutes%60} min ago'


def _human_forecast_lines(values: dict, kind: str) -> list[str]:
    if not values:
        return ['No provider values are stored yet.']
    if kind == 'marine':
        return [
            f"Swell: {values.get('swell_wave_height', values.get('wave_height', 'n/a'))} m from {values.get('swell_wave_direction', values.get('wave_direction', 'n/a'))}° at {values.get('swell_wave_period', values.get('wave_period', 'n/a'))} s.",
            f"Wind wave: {values.get('wind_wave_height', 'n/a')} m, direction {values.get('wind_wave_direction', 'n/a')}°, period {values.get('wind_wave_period', 'n/a')} s.",
            f"Sea-surface temperature: {values.get('sea_surface_temperature', 'n/a')} °C.",
            f"Current: {values.get('ocean_current_velocity', 'n/a')} m/s toward {values.get('ocean_current_direction', 'n/a')}°.",
        ]
    if kind == 'weather':
        return [
            f"Wind: {values.get('wind_speed_10m', 'n/a')} km/h from {values.get('wind_direction_10m', 'n/a')}°, gusting to {values.get('wind_gusts_10m', 'n/a')} km/h.",
            f"Air: {values.get('temperature_2m', 'n/a')} °C, cloud cover {values.get('cloud_cover', 'n/a')}%, precipitation {values.get('precipitation', 'n/a')} mm.",
            f"Visibility: {values.get('visibility', 'n/a')} m.",
        ]
    if kind == 'tide':
        return [
            f"Estimated water level: {values.get('water_level', 'n/a')} on a 0–1 local tide scale.",
            f"Tide is {values.get('state', 'unknown')}; next high in {values.get('time_to_next_high_hours', 'n/a')} h, next low in {values.get('time_to_next_low_hours', 'n/a')} h.",
            f"Change rate: {values.get('tidal_change_rate', 'n/a')} (estimated).",
        ]
    return [f"{k.replace('_',' ')}: {v}" for k, v in values.items()]


def _marine_values_for_spot(db, spot_id, start, end):
    rows = db.query(MarineForecast).filter(MarineForecast.spot_id==spot_id,MarineForecast.forecast_time>=start,MarineForecast.forecast_time<end).all()
    priority = {'mock-open-meteo-marine': 10, 'copernicus-marine': 20}
    latest_by_time_provider = {}
    for row in rows:
        key = (_aware(row.forecast_time), row.provider_name or '')
        current = latest_by_time_provider.get(key)
        if current is None or (_aware(row.fetched_at) or datetime.min.replace(tzinfo=UTC)) >= (_aware(current.fetched_at) or datetime.min.replace(tzinfo=UTC)):
            latest_by_time_provider[key] = row
    out = {}
    for row in sorted(latest_by_time_provider.values(), key=lambda r: (_aware(r.forecast_time), priority.get(r.provider_name or '', 0))):
        out[_aware(row.forecast_time)] = row.values
    return out


def _provider_points_near(points_by_time: dict[str, list[dict]], target_iso: str | None, max_minutes: int = 90) -> list[dict]:
    if not target_iso:
        return []
    try:
        target = datetime.fromisoformat(str(target_iso))
    except ValueError:
        return []
    latest_by_provider: dict[str, tuple[float, dict]] = {}
    for timestamp, points in points_by_time.items():
        try:
            point_time = datetime.fromisoformat(timestamp)
        except ValueError:
            continue
        delta = abs((point_time - target).total_seconds())
        if delta > max_minutes * 60:
            continue
        for point in points:
            provider = point.get('provider', 'unknown-provider')
            current = latest_by_provider.get(provider)
            if current is None or delta < current[0]:
                latest_by_provider[provider] = (delta, point)
    priority = {'copernicus-marine': 20, 'mock-open-meteo-marine': 10}
    return [point for _, point in sorted(latest_by_provider.values(), key=lambda item: (-priority.get(item[1].get('provider', ''), 0), item[1].get('provider', '')))]


def _marine_provider_points_for_spot(db, spot_id, start, end):
    rows = db.query(MarineForecast).filter(MarineForecast.spot_id==spot_id,MarineForecast.forecast_time>=start,MarineForecast.forecast_time<end).all()
    latest_by_time_provider: dict[tuple[str, str], MarineForecast] = {}
    for row in rows:
        forecast_time = _aware(row.forecast_time)
        if not forecast_time:
            continue
        provider = row.provider_name or 'unknown-provider'
        key = (forecast_time.isoformat(), provider)
        current = latest_by_time_provider.get(key)
        if current is None or (_aware(row.fetched_at) or datetime.min.replace(tzinfo=UTC)) >= (_aware(current.fetched_at) or datetime.min.replace(tzinfo=UTC)):
            latest_by_time_provider[key] = row
    out: dict[str, list[dict]] = {}
    provider_priority = {'mock-open-meteo-marine': 10, 'copernicus-marine': 20}
    for (timestamp, provider), row in sorted(latest_by_time_provider.items(), key=lambda item: (item[0][0], -provider_priority.get(item[0][1], 0), item[0][1])):
        values = row.values or {}
        wave_height = values.get('swell_wave_height', values.get('wave_height'))
        wave_direction = values.get('swell_wave_direction', values.get('wave_direction'))
        wave_period = values.get('swell_wave_period', values.get('wave_period'))
        entry = {
            'provider': provider,
            'timestamp': timestamp,
            'wave_height': wave_height,
            'wave_direction': wave_direction,
            'wave_period': wave_period,
            'total_wave_height': values.get('wave_height'),
            'total_wave_direction': values.get('wave_direction'),
            'total_wave_period': values.get('wave_period'),
            'wind_wave_height': values.get('wind_wave_height'),
            'tooltip': f"{provider} · swell {wave_height} m from {wave_direction}° @ {wave_period} s · total {values.get('wave_height')} m from {values.get('wave_direction')}° @ {values.get('wave_period')} s · wind wave {values.get('wind_wave_height')} m",
        }
        out.setdefault(timestamp, []).append(entry)
    return out


async def _ensure_copernicus_forecasts(db, spots, start, end):
    config = load_copernicus_config()
    if not config.is_ready:
        return None
    can_fetch, _ = provider_can_fetch(db, 'copernicus-marine', datetime.now(UTC))
    if not can_fetch:
        return _latest_fetch(db, 'copernicus-marine')
    output = config.cache_dir / 'wavewatch-copernicus-latest.nc'
    pf=ProviderFetch(provider_name='copernicus-marine',fetched_at=datetime.now(UTC),latitude=None,longitude=None,status='started',raw_response={'dataset_id':config.dataset_id,'variables':sorted(set((config.variable_map or {}).values()))},parsing_errors=None,data_age_seconds=None)
    db.add(pf); db.flush()
    try:
        await run_subset_download(config, aljezur_bbox(spots), start, end, output)
        for spot in spots:
            points = parse_copernicus_netcdf(output, spot.latitude, spot.longitude, config.variable_map or {}, 'copernicus-marine')
            for point in points:
                if start <= point.timestamp <= end:
                    db.add(MarineForecast(provider_fetch_id=pf.id,provider_name='copernicus-marine',spot_id=spot.id,forecast_time=point.timestamp,fetched_at=datetime.now(UTC),values=point.values,provider_status='healthy'))
        pf.status='healthy'; pf.raw_response={**(pf.raw_response or {}),'cache_file':str(output),'spot_count':len(spots)}
    except Exception as exc:
        pf.status='degraded'; pf.parsing_errors=str(exc)[:1000]
    db.commit()
    return pf


async def ensure_seed_forecasts(db):
    spots=db.query(SurfSpot).all(); now=datetime.now(UTC).replace(minute=0,second=0,microsecond=0); start=now-timedelta(hours=2); end=now+timedelta(hours=36)
    can_fetch, _ = provider_can_fetch(db, 'mock-open-meteo-fixture', datetime.now(UTC))
    if not can_fetch:
        if not db.query(DailyRecommendation).first():
            calculate_recommendations(db)
        return
    if db.query(MarineForecast).filter(MarineForecast.forecast_time>=now).first() and not can_fetch:
        return
    pf=ProviderFetch(provider_name='mock-open-meteo-fixture',fetched_at=datetime.now(UTC),latitude=None,longitude=None,status='healthy',raw_response={'fixture':'clean long-period north-west swell','rate_limit':'one provider fetch bundle every 30 minutes','scope':'marine + weather + tide prototype bundle'},parsing_errors=None,data_age_seconds=0); db.add(pf); db.flush()
    tide_points=await TideProvider().fetch_forecast(0,0,start,end)
    for spot in spots:
        for i in range(int((end-start).total_seconds()//3600)+1):
            ts=start+timedelta(hours=i); hour=ts.hour
            marine={'wave_height':1.4+(0.2 if hour>15 else 0),'wave_direction':310,'wave_period':12,'swell_wave_height':1.3+(0.3 if spot.slug in ['arrifana','amado'] else 0),'swell_wave_direction':315,'swell_wave_period':13,'wind_wave_height':0.4,'wind_wave_direction':285,'wind_wave_period':5,'sea_surface_temperature':18.5,'ocean_current_velocity':0.18,'ocean_current_direction':40}
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
            m=_marine_values_for_spot(db, spot.id, start, end)
            provider_points=_marine_provider_points_for_spot(db, spot.id, start, end)
            w={_aware(x.forecast_time):x.values for x in db.query(WeatherForecast).filter(WeatherForecast.spot_id==spot.id,WeatherForecast.forecast_time>=start,WeatherForecast.forecast_time<end).all()}
            t={_aware(x.forecast_time):x.values for x in db.query(TideForecast).filter(TideForecast.spot_id==spot.id,TideForecast.forecast_time>=start,TideForecast.forecast_time<end).all()}
            res=aggregate_daypart(spot, sorted(m.items()), w, t, daypart, profile='advanced')
            if not res: continue
            res['provider_points']=_provider_points_near(provider_points, res.get('forecast_time'))
            ss=SpotScore(spot_id=spot.id,daypart=daypart,score_date=score_date,score=res['score'],confidence_label=res['confidence_label'],classification=res['classification'],explanation=res['explanation'],summary=res,created_at=now); db.add(ss); db.flush(); scores.append(ss)
        if scores:
            ordered=sorted(scores, key=lambda s:s.score, reverse=True)
            top=ordered[0].score
            tied=[s for s in ordered if abs(s.score-top) <= 0.1]
            # Rotate exact ties by daypart so recommendations are data-derived but not permanently
            # pinned to the first seeded spot when prototype fixture conditions are identical.
            idx={'morning':0,'midday':1,'evening':2}.get(daypart,0) % len(tied)
            best=tied[idx]
            db.add(DailyRecommendation(score_date=score_date,daypart=daypart,spot_score_id=best.id,created_at=now))
    db.commit()

def _ns(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{k: _ns(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_ns(v) for v in value]
    return value


def calculate_rankings(db, score_date=None, profile='advanced'):
    """Calculate non-persisted daypart rankings for the selected proficiency."""
    profile = normalize_profile(profile)
    now=datetime.now(UTC); score_date=score_date or now.astimezone(__import__('zoneinfo').ZoneInfo('Europe/Lisbon')).date()
    windows=local_day_windows(score_date); spots=db.query(SurfSpot).all(); out={}
    for daypart,(start,end) in windows.items():
        rows=[]
        for spot in spots:
            if not spot.is_active_for_recommendations: continue
            m=_marine_values_for_spot(db, spot.id, start, end)
            provider_points=_marine_provider_points_for_spot(db, spot.id, start, end)
            w={_aware(x.forecast_time):x.values for x in db.query(WeatherForecast).filter(WeatherForecast.spot_id==spot.id,WeatherForecast.forecast_time>=start,WeatherForecast.forecast_time<end).all()}
            t={_aware(x.forecast_time):x.values for x in db.query(TideForecast).filter(TideForecast.spot_id==spot.id,TideForecast.forecast_time>=start,TideForecast.forecast_time<end).all()}
            res=aggregate_daypart(spot, sorted(m.items()), w, t, daypart, profile=profile)
            if not res: continue
            res['provider_points']=_provider_points_near(provider_points, res.get('forecast_time'))
            rows.append(SimpleNamespace(spot=spot, spot_id=spot.id, daypart=daypart, score=res['score'], confidence_label=res['confidence_label'], classification=res['classification'], explanation=res['explanation'], summary=_ns(res)))
        out[daypart]=sorted(rows, key=lambda r: r.score, reverse=True)
    return out


def spot_daypart_scores(db, spot, score_date=None, profile='advanced'):
    rankings=calculate_rankings(db, score_date, profile)
    return {part: next((r for r in rows if r.spot_id == spot.id), None) for part, rows in rankings.items()}


def provider_status(db):
    latest_marine=db.query(MarineForecast).order_by(desc(MarineForecast.fetched_at)).first()
    latest_weather=db.query(WeatherForecast).order_by(desc(WeatherForecast.fetched_at)).first()
    latest_tide=db.query(TideForecast).order_by(desc(TideForecast.fetched_at)).first()
    latest_copernicus=db.query(MarineForecast).filter(MarineForecast.provider_name=='copernicus-marine').order_by(desc(MarineForecast.fetched_at)).first()
    latest_copernicus_pub=db.query(CopernicusPublication).order_by(desc(CopernicusPublication.detected_at)).first()
    latest_copernicus_job=db.query(CopernicusIngestionJob).order_by(desc(CopernicusIngestionJob.created_at)).first()
    copernicus_fetch=_latest_fetch(db,'copernicus-marine')
    copernicus_config=load_copernicus_config()
    copernicus_missing=copernicus_config.missing_reasons
    fixture=_latest_fetch(db,'mock-open-meteo-fixture')
    can_fetch, last_fetch = provider_can_fetch(db, 'mock-open-meteo-fixture')
    next_fetch = (_aware(last_fetch) + PROVIDER_FETCH_INTERVAL).isoformat() if last_fetch and not can_fetch else 'available now'
    shared_rate = f"Protected by 30-minute bundle limit. Next external-style bundle: {next_fetch}."
    return {
        'open-meteo-marine': {
            'status':'healthy' if latest_marine else 'unavailable',
            'reason':'Marine forecast points are available from the latest protected provider bundle.' if latest_marine else 'No marine forecast has been stored yet.',
            'last_fetch': _fmt_age(fixture.fetched_at if fixture else None),
            'rate_limit': shared_rate,
            'human_data': _human_forecast_lines(latest_marine.values if latest_marine else {}, 'marine')
        },
        'open-meteo-weather': {
            'status':'healthy' if latest_weather else 'unavailable',
            'reason':'Weather forecast points are available and joined into surf scoring.' if latest_weather else 'No weather forecast has been stored yet.',
            'last_fetch': _fmt_age(fixture.fetched_at if fixture else None),
            'rate_limit': shared_rate,
            'human_data': _human_forecast_lines(latest_weather.values if latest_weather else {}, 'weather')
        },
        'ipma-open-data': {
            'status':'disabled',
            'reason':'Disabled by product decision: IPMA Open Data does not currently add useful spot-level accuracy for the Aljezur-focused app and would only act as broad fallback data.',
            'last_fetch':'not fetched',
            'rate_limit':'No IPMA requests are performed. Reconsider only if the app expands to additional Portuguese regions or a useful spot-level feed is selected.',
            'human_data':['IPMA is disabled. No IPMA values are fetched, stored, or used in scoring.']
        },
        'copernicus-marine': {
            'status': (latest_copernicus_job.status if latest_copernicus_job and latest_copernicus_job.status in ('queued','running') else (latest_copernicus_pub.status if latest_copernicus_pub else ('disabled' if copernicus_missing else 'waiting_for_publication'))),
            'reason': ('Copernicus Marine forecast values are stored and preferred for marine scoring.' if latest_copernicus else ('Not ready: ' + '; '.join(copernicus_missing) if copernicus_missing else 'Configured for publication-aware background ingestion; HTTP requests only read stored data.')),
            'last_fetch': _fmt_age((latest_copernicus_pub.ingestion_completed_at if latest_copernicus_pub and latest_copernicus_pub.ingestion_completed_at else copernicus_fetch.fetched_at if copernicus_fetch else None)),
            'rate_limit':'Publication-aware UTC windows: every 10 minutes 00:00-02:59 and 12:00-14:59, plus 18:30 reconciliation. Full downloads only after a new cycle is detected.',
            'human_data': [
                f"Product: {copernicus_config.product_id}",
                f"Dataset: {copernicus_config.dataset_id}",
                f"Latest publication: {latest_copernicus_pub.publication_identity if latest_copernicus_pub else 'none detected'}",
                *(_human_forecast_lines(latest_copernicus.values if latest_copernicus else {}, 'marine') if latest_copernicus else ['No Copernicus values are stored. No values are fabricated.'])
            ]
        },
        'astronomical-tide-estimate': {
            'status':'healthy' if latest_tide else 'unavailable',
            'reason':'Estimated tide points are calculated locally and clearly labelled as estimated.' if latest_tide else 'No tide estimate has been stored yet.',
            'last_fetch': _fmt_age(fixture.fetched_at if fixture else None),
            'rate_limit':'Local calculation is refreshed with the protected forecast bundle, not continuously polled.',
            'human_data': _human_forecast_lines(latest_tide.values if latest_tide else {}, 'tide')
        },
        'buoy-observations': {
            'status':'disabled',
            'reason':'Future observation interface exists; no stable machine-readable buoy feed is enabled yet.',
            'last_fetch':'not fetched',
            'rate_limit':'Will use the same 30-minute bundle limit when enabled.',
            'human_data':['No buoy observation values are stored yet.']
        },
        'webcam-confirmation': {
            'status':'disabled',
            'reason':'Third-party webcams are not scraped or analyzed without a permitted interface.',
            'last_fetch':'not fetched',
            'rate_limit':'No webcam requests are performed.',
            'human_data':['No webcam data is ingested. Future licensed confirmation can unlock Live confirmed confidence.']
        },
    }
