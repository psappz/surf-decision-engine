import os, re, tempfile
from fastapi.testclient import TestClient
import pytest

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
    try: os.remove(path)
    except OSError: pass

def login(c,u='David',p='surferking'):
    return c.post('/login', data={'username':u,'password':p}, follow_redirects=False)

def csrf(html):
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

def spot_slugs():
    from app.database import SessionLocal
    from app.models import SurfSpot
    db=SessionLocal()
    try:
        return [s.slug for s in db.query(SurfSpot).order_by(SurfSpot.name).limit(7).all()]
    finally:
        db.close()

def test_user_can_toggle_favourite_from_surf_table_and_detail(client):
    login(client)
    page=client.get('/surf')
    assert page.status_code == 200
    assert '<th>Favourite</th>' in page.text
    token=csrf(page.text)
    slug=spot_slugs()[0]
    add=client.post(f'/surf/spots/{slug}/favorite', data={'csrf_token':token,'favorite':'on','next':'/surf'}, follow_redirects=False)
    assert add.status_code == 303
    page=client.get('/surf')
    assert 'Favourite surf spots: 1/5' in page.text
    detail=client.get(f'/surf/spots/{slug}')
    assert '<dt>Favourite</dt>' in detail.text
    assert 'Selected as a favourite' in detail.text
    token=csrf(detail.text)
    remove=client.post(f'/surf/spots/{slug}/favorite', data={'csrf_token':token,'next':f'/surf/spots/{slug}'}, follow_redirects=False)
    assert remove.status_code == 303
    assert 'Not selected as a favourite' in client.get(f'/surf/spots/{slug}').text

def test_favourite_limit_disables_unselected_stars_and_server_blocks_sixth(client):
    login(client)
    slugs=spot_slugs()
    token=csrf(client.get('/surf').text)
    for slug in slugs[:5]:
        assert client.post(f'/surf/spots/{slug}/favorite', data={'csrf_token':token,'favorite':'on','next':'/surf'}, follow_redirects=False).status_code == 303
        token=csrf(client.get('/surf').text)
    page=client.get('/surf')
    assert 'Favourite surf spots: 5/5' in page.text
    assert 'You already selected 5 favourites' in page.text
    # Existing favourites stay enabled so the user can unselect them; unselected stars become inactive.
    assert 'checked' in page.text
    assert 'disabled' in page.text
    sixth=client.post(f'/surf/spots/{slugs[5]}/favorite', data={'csrf_token':csrf(page.text),'favorite':'on','next':'/surf'}, follow_redirects=False)
    assert sixth.status_code == 303
    assert 'favorite_limit=1' in sixth.headers['location']
    page=client.get('/surf?favorite_limit=1')
    assert 'You can select up to 5 favourite surf spots' in page.text
    detail=client.get(f'/surf/spots/{slugs[5]}')
    assert 'Not selected as a favourite' in detail.text
    assert 'disabled' in detail.text

def test_favourites_are_per_user(client):
    slugs=spot_slugs(); login(client,'David','surferking')
    token=csrf(client.get('/surf').text)
    client.post(f'/surf/spots/{slugs[0]}/favorite', data={'csrf_token':token,'favorite':'on','next':'/surf'}, follow_redirects=False)
    client.get('/logout')
    login(client,'Loliking','loliwave')
    page=client.get('/surf')
    assert 'Favourite surf spots: 0/5' in page.text
