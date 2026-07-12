import io, os, re, tempfile
from PIL import Image
from fastapi.testclient import TestClient
import pytest

@pytest.fixture()
def client(monkeypatch):
    fd,path=tempfile.mkstemp(suffix='.db'); os.close(fd)
    media=tempfile.mkdtemp(prefix='wavewatch-media-')
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{path}')
    monkeypatch.setenv('MEDIA_ROOT', media)
    import importlib, app.config, app.database, app.models, app.main
    importlib.reload(app.config); importlib.reload(app.database); importlib.reload(app.models)
    import app.security, app.seed, app.forecast_service, app.main
    importlib.reload(app.security); importlib.reload(app.seed); importlib.reload(app.forecast_service); importlib.reload(app.main)
    with TestClient(app.main.app) as c: yield c

def login(c,u,p):
    r=c.post('/login', data={'username':u,'password':p}, follow_redirects=False); c.cookies.set('ww_session', r.cookies['ww_session']); return r

def csrf(html):
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

def img_bytes(fmt='JPEG'):
    im=Image.new('RGB',(32,24),(20,120,200)); b=io.BytesIO(); im.save(b,fmt); return b.getvalue()

def test_authorization_for_admin_and_mod(client):
    login(client,'Patrick','loliking'); assert client.get('/adm').status_code==200; assert client.get('/mod').status_code==200
    client.cookies.clear(); login(client,'Loliking','loliwave'); assert client.get('/adm').status_code==404; assert client.get('/mod').status_code==200
    client.cookies.clear(); login(client,'David','surferking'); assert client.get('/adm').status_code==404; assert client.get('/mod').status_code==404

def test_admin_spot_edit_validation_and_webcams(client):
    from app.database import SessionLocal
    from app.models import SurfSpot, SpotWebcam
    login(client,'Patrick','loliking'); db=SessionLocal(); spot=db.query(SurfSpot).filter_by(slug='odeceixe').one(); old=spot.name; old_updated=spot.updated_at; other=db.query(SurfSpot).filter(SurfSpot.id!=spot.id).first(); db.close()
    page=client.get(f'/adm/spots/{spot.id}'); token=csrf(page.text)
    bad=client.post(f'/adm/spots/{spot.id}', data={'csrf_token':token,'code':spot.code,'slug':other.slug,'name':'Changed','latitude':'999','longitude':str(spot.longitude)}, follow_redirects=False)
    assert bad.status_code==400 and 'Slug already exists' in bad.text and 'Latitude must be between' in bad.text
    db=SessionLocal(); assert db.get(SurfSpot, spot.id).name==old; db.close()
    good={k:(getattr(spot,k) if getattr(spot,k) is not None else '') for k in ['code','slug','name','beach_name','zone_name','latitude','longitude','description','spot_type','difficulty','preferred_swell_direction_min','preferred_swell_direction_max','acceptable_swell_direction_min','acceptable_swell_direction_max','preferred_swell_height_min','preferred_swell_height_max','maximum_safe_swell_height_for_profile','preferred_period_min','preferred_period_max','preferred_wind_direction_min','preferred_wind_direction_max','preferred_tide_min','preferred_tide_max','tide_preference','exposure_factor','shelter_factor','hazards','access_notes','base_confidence','external_navigation_url','access_map_id','access_map_asset','access_map_status','seed_source_note']}
    good.update({'csrf_token':token,'name':'Odeceixe Edited','is_active_for_recommendations':'on'})
    assert client.post(f'/adm/spots/{spot.id}', data=good, follow_redirects=False).status_code==303
    add={'csrf_token':token,'title':'Operator Cam A','operator_name':'Operator A','url':'https://operator-a.example/cam','is_active':'on'}
    assert client.post(f'/adm/spots/{spot.id}/webcams', data=add, follow_redirects=False).status_code==303
    add['title']='Operator Cam B'; add['url']='https://operator-b.example/cam'; assert client.post(f'/adm/spots/{spot.id}/webcams', data=add, follow_redirects=False).status_code==303
    assert client.post(f'/adm/spots/{spot.id}/webcams', data={**add,'url':'javascript:alert(1)'}, follow_redirects=False).status_code==400
    detail=client.get('/surf/spots/odeceixe').text
    assert 'Nearby webcam check' not in detail and 'Windy' not in detail
    assert 'Operator Cam A' in detail and 'target="_blank"' in detail and 'rel="noopener noreferrer"' in detail
    db=SessionLocal(); assert db.get(SurfSpot, spot.id).updated_at != old_updated; assert db.query(SpotWebcam).filter_by(spot_id=spot.id).count()==2; db.close()

def test_webcam_suggestion_approval_reject_and_duplicate(client):
    from app.database import SessionLocal
    from app.models import SurfSpot, WebcamSuggestion, SpotWebcam
    login(client,'David','surferking'); page=client.get('/surf/spots/odeceixe'); token=csrf(page.text)
    data={'csrf_token':token,'suggested_url':'https://owner.example/live','suggested_title':'Owner cam','suggested_operator_name':'Owner','submitter_note':'near beach'}
    assert client.post('/surf/spots/odeceixe/webcam-suggestions', data=data, follow_redirects=False).status_code==303
    assert client.post('/surf/spots/odeceixe/webcam-suggestions', data=data, follow_redirects=False).status_code==400
    assert 'Owner cam' not in client.get('/surf/spots/odeceixe').text
    db=SessionLocal(); sug=db.query(WebcamSuggestion).one(); assert sug.status=='pending'; sid=sug.id; db.close()
    assert client.post(f'/mod/webcam-suggestions/{sid}/approve', data={'csrf_token':token}, follow_redirects=False).status_code in (403,404)
    client.cookies.clear(); login(client,'Loliking','loliwave'); mod=client.get('/mod'); mtok=csrf(mod.text)
    assert client.post(f'/mod/webcam-suggestions/{sid}/approve', data={'csrf_token':mtok,'title':'Reviewed owner cam','operator_name':'Owner','url':'https://owner.example/live'}, follow_redirects=False).status_code==303
    assert client.post(f'/mod/webcam-suggestions/{sid}/approve', data={'csrf_token':mtok}, follow_redirects=False).status_code==303
    db=SessionLocal(); assert db.query(SpotWebcam).count()==1; assert db.get(WebcamSuggestion,sid).status=='approved'; db.close()
    assert 'Reviewed owner cam' in client.get('/surf/spots/odeceixe').text
    # rejection path
    client.cookies.clear(); login(client,'David','surferking'); token=csrf(client.get('/surf/spots/arrifana').text)
    client.post('/surf/spots/arrifana/webcam-suggestions', data={**data,'csrf_token':token,'suggested_url':'https://owner.example/arrifana'}, follow_redirects=False)
    db=SessionLocal(); rid=db.query(WebcamSuggestion).filter_by(status='pending').one().id; db.close()
    client.cookies.clear(); login(client,'Patrick','loliking'); mtok=csrf(client.get('/mod').text)
    assert client.post(f'/mod/webcam-suggestions/{rid}/reject', data={'csrf_token':mtok,'moderator_note':'aggregator'}, follow_redirects=False).status_code==303

def test_photo_upload_processing_and_security(client):
    from app.database import SessionLocal
    from app.models import SpotPhoto
    anon=client.post('/surf/spots/odeceixe/photos', data={'csrf_token':'x'}, files={'images':('x.jpg',img_bytes(),'image/jpeg')}, follow_redirects=False)
    assert anon.status_code in (303,403)
    login(client,'David','surferking'); page=client.get('/surf/spots/odeceixe'); token=csrf(page.text)
    files=[('images',('..evil.jpg',img_bytes('JPEG'),'image/jpeg')),('images',('photo.png',img_bytes('PNG'),'image/png')),('images',('photo.webp',img_bytes('WEBP'),'image/webp'))]
    assert client.post('/surf/spots/odeceixe/photos', data={'csrf_token':token,'caption':'Set check'}, files=files, follow_redirects=False).status_code==303
    assert client.post('/surf/spots/odeceixe/photos', data={'csrf_token':token}, files={'images':('bad.svg',b'<svg></svg>','image/svg+xml')}, follow_redirects=False).status_code==400
    assert client.post('/surf/spots/odeceixe/photos', data={'csrf_token':token}, files={'images':('fake.jpg',b'not image','image/jpeg')}, follow_redirects=False).status_code==400
    db=SessionLocal(); photos=db.query(SpotPhoto).all(); assert len(photos)==3
    p=photos[0]; assert '..evil' not in p.display_path and p.stored_mime_type=='image/webp' and p.thumbnail_path.endswith('thumbnail.webp')
    media=client.get('/media/'+p.thumbnail_path); assert media.status_code==200 and media.headers['x-content-type-options']=='nosniff'
    p.status='hidden'; db.commit(); db.close()
    assert '/media/'+p.thumbnail_path not in client.get('/surf/spots/odeceixe').text
