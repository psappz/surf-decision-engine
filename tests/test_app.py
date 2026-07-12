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
    login_page = client.get('/login')
    assert login_page.status_code == 200
    assert 'wavewatch-logo' not in login_page.text
    assert 'top-preferences' not in login_page.text
    assert 'name="lang"' not in login_page.text
    assert 'name="proficiency"' not in login_page.text
    assert 'WaveWatch' not in login_page.text
    assert 'Onda' not in login_page.text
    assert 'Experto' not in login_page.text
    assert 'onda-experto24-logo' not in login_page.text
    assert 'Paddle' not in login_page.text
    bad=client.post('/login', data={'username':'Patrick','password':'wrong'})
    assert bad.status_code==401 and 'Invalid username or password' in bad.text
    ok=login(client,'patrick','loliking')
    assert ok.status_code==303 and ok.headers['location']=='/surf'
    assert 'ww_session' in ok.headers.get('set-cookie','')

def test_session_protection_redirect_logout_role_persistence(client):
    assert client.get('/surf', follow_redirects=False).status_code==303
    r=login(client,'Loliking','loliwave'); client.cookies.set('ww_session', r.cookies['ww_session'])
    page=client.get('/surf')
    assert 'Loliking' not in page.text and 'moderator' not in page.text
    assert 'onda-experto24-logo.png' in page.text
    assert 'action="/logout"' not in page.text
    assert '>logout</a>' in page.text
    out=client.get('/logout', follow_redirects=False)
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
    assert h['providers']['ipma-open-data']['status']=='disabled'
    assert h['providers']['open-meteo-marine']['status']=='healthy'
    assert '30-minute bundle limit' in h['providers']['open-meteo-marine']['rate_limit']
    p=client.get('/surf')
    assert 'Best surf spot of the day' in p.text and 'Morning' in p.text and 'Evening' in p.text
    assert 'data-provider-button' in p.text and 'Human-readable data fetched' in p.text
    assert 'Shaka' not in p.text  # avoid decorative term stuffing when not applicable

def test_provider_bundle_rate_limit(client):
    from app.database import SessionLocal
    from app.models import ProviderFetch
    from app.forecast_service import provider_can_fetch, PROVIDER_FETCH_INTERVAL
    from datetime import datetime, timedelta, UTC
    db=SessionLocal()
    first=db.query(ProviderFetch).filter_by(provider_name='mock-open-meteo-fixture').first()
    assert first is not None
    allowed,last=provider_can_fetch(db,'mock-open-meteo-fixture', datetime.now(UTC))
    assert allowed is False and last is not None
    allowed_later,_=provider_can_fetch(db,'mock-open-meteo-fixture', datetime.now(UTC)+PROVIDER_FETCH_INTERVAL+timedelta(seconds=1))
    assert allowed_later is True
    db.close()

def test_google_maps_url_spot_detail_and_all_routes(client):
    r=login(client,'David','surferking'); client.cookies.set('ww_session', r.cookies['ww_session'])
    page=client.get('/surf/spots/odeceixe')
    assert page.status_code==200
    assert 'https://www.google.com/maps/search/?api=1&query=' in page.text
    assert 'https://www.openstreetmap.org/?mlat=' in page.text
    assert 'Live webcams' in page.text
    assert 'Windy webcams' in page.text
    assert 'Odeceixe live webcam' in page.text
    assert 'https://beachcam.meo.pt/livecams/odeceixe' in page.text
    assert 'https://www.windy.com/37.442/-8.798?37.442,-8.798,13' in page.text
    assert '<iframe' not in page.text
    assert 'Access sketch' not in page.text
    assert 'Access map pending verification' not in page.text
    assert '/static/access-maps/' not in page.text
    from app.database import SessionLocal
    from app.models import SurfSpot
    db=SessionLocal()
    try:
        spot=db.query(SurfSpot).filter_by(slug='odeceixe').one()
        assert spot.access_map_id is None
        assert spot.access_map_asset is None
    finally:
        db.close()
    assert 'onda-experto24-logo.png' in page.text
    assert 'wavewatch-logo.png' not in page.text
    assert 'action="/logout"' not in page.text
    assert '>logout</a>' in page.text
    assert 'spot-media' not in page.text
    assert 'spot-media-unavailable' not in page.text
    assert '/static/spot-media/odeceixe-beach.svg' not in page.text
    assert '/static/spot-media/odeceixe-map.svg' not in page.text
    assert 'Strandbild nicht verfügbar' not in page.text
    assert 'Landkartenausschnitt nicht verfügbar' not in page.text
    assert 'Odeceixe' in page.text

def test_authenticated_header_uses_white_background_and_no_hero_image():
    css = open('app/static/style.css', encoding='utf-8').read()
    assert '.app-header' in css
    assert "background:#fff" in css
    assert "wavewatch-hero-logo" not in css
    assert "image-set(" not in css


def test_no_permanent_hardcoded_recommendation(client):
    from app.database import SessionLocal
    from app.models import DailyRecommendation
    db=SessionLocal(); recs=[r.spot_score.spot.slug for r in db.query(DailyRecommendation).all()]
    assert recs and len(set(recs)) >= 1
    assert not all(x=='odeceixe' for x in recs)
    db.close()


def test_i18n_language_and_proficiency_controls(client):
    r=login(client,'Patrick','loliking'); client.cookies.set('ww_session', r.cookies['ww_session'])
    client.get('/preferences?lang=de&proficiency=beginner&next=/surf', follow_redirects=False)
    page=client.get('/surf')
    assert 'Surfspot des Tages' in page.text
    assert 'Schwierigkeitspräferenz' in page.text
    assert 'Wasser\xadtemperatur' in page.text
    assert 'Anfänger' in page.text
    assert 'Zweit- und drittbeste Alternativen' in page.text
    assert '<th>Surf Call</th>' in page.text
    client.get('/preferences?lang=pt&proficiency=pro&next=/surf', follow_redirects=False)
    pt=client.get('/surf')
    assert 'Melhor surf spot do dia' in pt.text
    assert 'Preferência de dificuldade' in pt.text


def test_admin_page_beach_spot_user_and_audit(client):
    # no public navigation link; admins remember /adm
    r=login(client,'Patrick','loliking'); client.cookies.set('ww_session', r.cookies['ww_session'])
    surf=client.get('/surf')
    assert surf.status_code == 200 and 'href="/adm"' not in surf.text
    adm=client.get('/adm')
    assert adm.status_code == 200
    assert 'WaveWatch admin' in adm.text and 'Add beach' in adm.text and 'Create new user' in adm.text
    assert 'Last 5 user logins' in adm.text and 'data-user-modal' in adm.text
    beach=client.post('/adm/beaches', data={'name':'Praia Test Admin','latitude':'37.1','longitude':'-8.9','webcam_urls':'https://example.test/beachcam'}, files={'images':('beach.jpg',b'img','image/jpeg')}, follow_redirects=False)
    assert beach.status_code == 303
    from app.database import SessionLocal
    from app.models import Beach, SurfSpot, User, LoginEvent, PageAccess, MediaAsset, WebcamLink
    db=SessionLocal()
    b=db.query(Beach).filter_by(name='Praia Test Admin').one()
    assert b.webcam_urls == ['https://example.test/beachcam']
    assert db.query(MediaAsset).filter_by(entity_type='beach', entity_id=b.id).count() == 1
    assert db.query(WebcamLink).filter_by(entity_type='beach', entity_id=b.id).count() == 1
    db.close()
    spot=client.post('/adm/spots', data={'beach_id':str(b.id),'name':'Admin Peak','latitude':'37.11','longitude':'-8.91','webcam_urls':'https://example.test/spotcam'}, files={'images':('spot.jpg',b'img','image/jpeg')}, follow_redirects=False)
    assert spot.status_code == 303
    user_resp=client.post('/adm/users', data={'username':'NewSurfer','temp_password':'temp12345'}, follow_redirects=False)
    assert user_resp.status_code == 303
    db=SessionLocal()
    try:
        assert db.query(SurfSpot).filter_by(slug='admin-peak').one().webcam_url == 'https://example.test/spotcam'
        assert db.query(User).filter_by(username_lower='newsurfer').one().role == 'user'
        assert db.query(LoginEvent).count() >= 1
        assert db.query(PageAccess).filter(PageAccess.path=='/adm').count() >= 1
    finally: db.close()
    client.cookies.clear(); nr=login(client,'NewSurfer','temp12345'); client.cookies.set('ww_session', nr.cookies['ww_session'])
    assert client.get('/adm').status_code == 404


def test_loliking_and_david_default_to_german(client):
    for username,password in [('Loliking','loliwave'),('David','surferking')]:
        client.cookies.clear()
        r=login(client, username, password); client.cookies.set('ww_session', r.cookies['ww_session'])
        page=client.get('/surf')
        assert 'Surfspot des Tages' in page.text
        assert '<option value="de" selected>Deutsch</option>' in page.text


def test_proficiency_changes_recommendation_scores(client):
    r=login(client,'Patrick','loliking'); client.cookies.set('ww_session', r.cookies['ww_session'])
    beginner=client.get('/surf?proficiency=beginner').text
    pro=client.get('/surf?proficiency=pro').text
    assert beginner != pro
    assert 'Beginner' in beginner
    assert 'Pro' in pro
