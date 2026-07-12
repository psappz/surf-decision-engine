from datetime import datetime, timedelta, UTC
from statistics import median
from zoneinfo import ZoneInfo
import math
DAYPARTS={'morning':(6,11),'midday':(11,16),'evening':(16,21)}
def in_direction_range(angle, start, end):
    angle%=360; start%=360; end%=360
    return start<=angle<=end if start<=end else angle>=start or angle<=end
def angular_diff(a,b): return abs((a-b+180)%360-180)
def fit_range(v, lo, hi, pts):
    if v is None: return 0
    if lo<=v<=hi: return pts
    dist=min(abs(v-lo), abs(v-hi)); return max(0, pts - dist*pts/max(hi-lo,1))
def direction_score(angle, pref_min, pref_max, acc_min, acc_max, pts):
    if angle is None: return 0
    if in_direction_range(angle,pref_min,pref_max): return pts
    if in_direction_range(angle,acc_min,acc_max): return pts*.45
    return 0
def classify(score):
    return 'excellent' if score>=78 else 'good' if score>=62 else 'workable' if score>=45 else 'poor'
def confidence_label(score, providers=1, stale=False, missing=0):
    if stale or missing>3 or score<.45: return 'Uncertain'
    if providers>=2 and score>=.72: return 'Well supported'
    return 'Estimated'
def estimated_breaking_range(spot, marine, tide):
    h=marine.get('swell_wave_height') or marine.get('wave_height') or 0
    period=marine.get('swell_wave_period') or marine.get('wave_period') or 8
    d=marine.get('swell_wave_direction') or marine.get('wave_direction') or 300
    dirfit=1.0 if in_direction_range(d, spot.acceptable_swell_direction_min, spot.acceptable_swell_direction_max) else .65
    energy=1 + max(0,min(period-8,8))*0.03
    tide_adj=.95 if tide and tide.get('water_level') in (None,) else 1.0
    face=h*(spot.exposure_factor or 1)*(spot.shelter_factor or 1)*dirfit*energy*tide_adj
    return (round(max(0,face*.8),1), round(max(.1,face*1.25),1))
PROFICIENCY_PROFILES={
    'beginner': {'height':(.35,.9),'max':1.25,'hazard':24,'advanced_fit':1,'period':(6,11)},
    'rookie': {'height':(.45,1.15),'max':1.55,'hazard':18,'advanced_fit':2,'period':(7,12)},
    'intermediate': {'height':(.65,1.65),'max':2.25,'hazard':10,'advanced_fit':3,'period':(8,14)},
    'advanced': {'height':None,'max':None,'hazard':5,'advanced_fit':5,'period':None},
    'pro': {'height':(.9,2.5),'max':3.8,'hazard':3,'advanced_fit':5,'period':(10,18)},
}
def normalize_profile(profile):
    return profile if profile in PROFICIENCY_PROFILES else 'advanced'
def score_point(spot, marine, weather, tide, data_age_hours=0, provider_agreement=.7, profile='advanced'):
    profile=normalize_profile(profile); prof=PROFICIENCY_PROFILES[profile]
    missing=sum(1 for v in [marine.get('swell_wave_height') or marine.get('wave_height'), marine.get('swell_wave_direction') or marine.get('wave_direction'), marine.get('swell_wave_period') or marine.get('wave_period'), weather.get('wind_speed_10m'), weather.get('wind_direction_10m')] if v is None)
    h=marine.get('swell_wave_height') or marine.get('wave_height'); d=marine.get('swell_wave_direction') or marine.get('wave_direction'); p=marine.get('swell_wave_period') or marine.get('wave_period')
    ws=weather.get('wind_speed_10m'); wd=weather.get('wind_direction_10m')
    score=0
    score+=direction_score(d,spot.preferred_swell_direction_min,spot.preferred_swell_direction_max,spot.acceptable_swell_direction_min,spot.acceptable_swell_direction_max,20)
    hlo,hhi = prof['height'] or (spot.preferred_swell_height_min, spot.preferred_swell_height_max)
    plo,phi = prof['period'] or (spot.preferred_period_min, spot.preferred_period_max)
    score+=fit_range(h,hlo,hhi,15)
    score+=fit_range(p,plo,phi,15)
    score+=15 if wd is not None and in_direction_range(wd,spot.preferred_wind_direction_min,spot.preferred_wind_direction_max) else (5 if wd is not None else 0)
    score+=max(0,10-(ws or 0)*.7) if ws is not None else 0
    score+=10 if tide and (spot.preferred_tide_min <= tide.get('water_level',.5) <= spot.preferred_tide_max) else 5
    score+=min(5,max(0,(spot.exposure_factor or 1)*3))
    diff=(spot.difficulty or '').lower(); hazard_type=any(w in (spot.spot_type or '').lower() for w in ['reef','rock'])
    if profile in ['beginner','rookie'] and ('advanced' in diff or hazard_type):
        score+=prof['advanced_fit']
    elif profile=='intermediate' and hazard_type:
        score+=2
    else:
        score+=prof['advanced_fit']
    score+=provider_agreement*3
    score+=0 if data_age_hours>12 else 2
    penalties=[]
    max_safe = prof['max'] or (spot.maximum_safe_swell_height_for_profile or 3.5)
    if h and h>max_safe: penalties.append(('unsafe wave height for selected level',25))
    if ws and ws>28: penalties.append(('extreme gusts or strong wind',15))
    if ws and wd is not None and not in_direction_range(wd,spot.preferred_wind_direction_min,spot.preferred_wind_direction_max): penalties.append(('onshore or cross-onshore wind',8))
    if missing: penalties.append(('missing core parameters',missing*5))
    if data_age_hours>6: penalties.append(('stale data',min(20,data_age_hours)))
    if (spot.base_confidence or 0)<.55: penalties.append(('low base confidence',10))
    if hazard_type: penalties.append(('reef or rock hazard',prof['hazard']))
    if profile in ['beginner','rookie'] and 'advanced' in diff: penalties.append(('spot difficulty above selected level',18 if profile=='beginner' else 12))
    if profile=='intermediate' and hazard_type: penalties.append(('technical take-off for selected level',7))
    for _,pnt in penalties: score-=pnt
    score=max(0,min(100,round(score,1)))
    cbase=(spot.base_confidence or .5) + provider_agreement*.15 - missing*.08 - (0.2 if data_age_hours>6 else 0)
    br=estimated_breaking_range(spot, marine, tide or {})
    explanation=f"{spot.name} scores {classify(score)} because swell direction/period, wind, tide and spot exposure were matched against provisional {profile}-surfer rules."
    if penalties: explanation += " Main cautions: " + ", ".join(x for x,_ in penalties[:3]) + "."
    return {'score':score,'confidence_label':confidence_label(cbase,2 if provider_agreement>.75 else 1,data_age_hours>12,missing),'classification':classify(score),'penalties':penalties,'estimated_breaking_range':br,'explanation':explanation}
def local_day_windows(day, tz='Europe/Lisbon'):
    z=ZoneInfo(tz); out={}
    for name,(a,b) in DAYPARTS.items():
        start=datetime(day.year,day.month,day.day,a,tzinfo=z).astimezone(UTC); end=datetime(day.year,day.month,day.day,b,tzinfo=z).astimezone(UTC); out[name]=(start,end)
    return out
def aggregate_daypart(spot, marine_points, weather_points, tide_points, daypart, profile='advanced'):
    def nearest_values(points, target, max_minutes=90):
        if not isinstance(points, dict) or not points:
            return {}
        best_time = min(points.keys(), key=lambda ts: abs((ts - target).total_seconds()))
        if abs((best_time - target).total_seconds()) <= max_minutes * 60:
            return points.get(best_time, {}) or {}
        return {}
    vals=[]; summaries=[]
    for t,m in marine_points:
        w=nearest_values(weather_points,t); tide=nearest_values(tide_points,t)
        res=score_point(spot,m,w,tide, profile=profile); vals.append(res['score']); summaries.append((res,m,w,tide,t))
    if not vals: return None
    volatility=max(vals)-min(vals) if len(vals)>1 else 0; med=max(0, median(vals)-volatility*.15); best=max(summaries,key=lambda x:x[0]['score'])
    res=dict(best[0]); res['score']=round(med,1); res['forecast_time']=best[4].isoformat(); res['marine']=best[1]; res['weather']=best[2]; res['tide']=best[3]; return res
