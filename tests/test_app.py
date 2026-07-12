import os, tempfile
from datetime import datetime, timedelta, UTC, date
import pytest
from fastapi.testclient import TestClient

@pytest.fixture()
def client(monkeypatch):
    fd,path=tempfile.mkstemp(suffix='.db'); os.close(fd)
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{path}')
    import importlib, app.config, app.database, app.models, app.main
    importlib.reload(app.config); importlib.reload(app.database); importlib.reload(app.models)
    import app.security, app.seed, app.forecast_service, app.main
    importlib.reload(app.security); importlib.reload(app.seed); importlib.reload(app.forecast_service); importlib.reload(app.main)
    with TestClient(app.main.app) as c:
        yield c

def login(c,u='Patrick',p='loliking'):
    return c.post('/login', data={'username':u,'password':p}, follow_redirects=False)

def test_success_failed_login_and_case_insensitive(client):
    bad=client.post('/login', data={'username':'Patrick','password':'wrong'})
    assert bad.status_code==401 and 'Invalid username or password' in bad.text
    ok=login(client,'patrick','loliking')
    assert ok.status_code==303 and ok.headers['location']=='/surf'
    assert 'ww_session' in ok.headers.get('set-cookie','')

def test_session_protection_redirect_logout_role_persistence(client):
    assert client.get('/surf', follow_redirects=False).status_code==303
    r=login(client,'Loliking','loliwave'); client.cookies.set('ww_session', r.cookies['ww_session'])
    page=client.get('/surf')
    assert 'Loliking' in page.text and 'moderator' in page.text
    import re
    token=re.search('name="csrf_token" value="([^"]+)"', page.text).group(1)
    out=client.post('/logout', data={'csrf_token':token}, follow_redirects=False)
    assert out.status_code==303
    assert client.get('/surf', follow_redirects=False).status_code==303

def test_seed_idempotency(client):
    from app.database import SessionLocal
    from app.models import User, SurfSpot
    from app.seed import seed
    db=SessionLocal(); users1=db.query(User).count(); spots1=db.query(SurfSpot).count(); db.close()
    seed(); db=SessionLocal(); assert db.query(User).count()==users1 and db.query(SurfSpot).count()==spots1; db.close()

def test_direction_wraparound():
    from app.scoring import in_direction_range
    assert in_direction_range(350,315,30)
    assert in_direction_range(10,315,30)
    assert not in_direction_range(120,315,30)

def test_spot_scoring_safety_stale_confidence_tide():
    from app.database import SessionLocal
    from app.models import SurfSpot
    from app.scoring import score_point
    db=SessionLocal(); spot=db.query(SurfSpot).filter_by(slug='arrifana-reef').first()
    res=score_point(spot, {'swell_wave_height':1.6,'swell_wave_direction':315,'swell_wave_period':14}, {'wind_speed_10m':8,'wind_direction_10m':100}, {'water_level':.5,'state':'rising'})
    assert 0 <= res['score'] <= 100 and res['classification'] in ['excellent','good','workable','poor']
    unsafe=score_point(spot, {'swell_wave_height':5,'swell_wave_direction':315,'swell_wave_period':14}, {'wind_speed_10m':8,'wind_direction_10m':100}, {'water_level':.5})
    assert unsafe['score'] < res['score'] and any('unsafe' in p[0] for p in unsafe['penalties'])
    stale=score_point(spot, {'swell_wave_height':1.6}, {}, {'water_level':.5}, data_age_hours=18)
    assert stale['confidence_label']=='Uncertain'
    db.close()

def test_provider_failure_fallback_and_daypart_recommendations(client):
    r=login(client,'Patrick','loliking'); client.cookies.set('ww_session', r.cookies['ww_session'])
    h=client.get('/health').json()
    assert h['providers']['ipma-open-data']=='degraded'
    p=client.get('/surf')
    assert 'Best surf spot of the day' in p.text and 'Morning' in p.text and 'Evening' in p.text

def test_google_maps_url_spot_detail_and_all_routes(client):
    r=login(client,'David','surferking'); client.cookies.set('ww_session', r.cookies['ww_session'])
    page=client.get('/surf/spots/odeceixe')
    assert page.status_code==200
    assert 'https://www.google.com/maps/search/?api=1&query=' in page.text
    assert 'Odeceixe' in page.text

def test_no_permanent_hardcoded_recommendation(client):
    from app.database import SessionLocal
    from app.models import DailyRecommendation
    db=SessionLocal(); recs=[r.spot_score.spot.slug for r in db.query(DailyRecommendation).all()]
    assert recs and len(set(recs)) >= 1
    assert not all(x=='odeceixe' for x in recs)
    db.close()
