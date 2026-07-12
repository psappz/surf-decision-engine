from datetime import datetime, UTC
from zoneinfo import ZoneInfo
from pathlib import Path
import re, secrets
from fastapi import FastAPI, Request, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy import desc
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from .database import get_db, SessionLocal, engine
from .models import Base, User, SurfSpot, SpotScore, DailyRecommendation, MarineForecast, Session as DbSession, Beach, LoginEvent, PageAccess, MediaAsset, WebcamLink
from .security import verify_password, hash_password, rate_limited, record_failure, clear_failures, create_session, get_session, destroy_session, set_session_cookie, clear_session_cookie
from .seed import seed
from .forecast_service import ensure_seed_forecasts, calculate_recommendations, provider_status, calculate_rankings, spot_daypart_scores
from .access_maps import osm_link
from .config import settings
from .i18n import normalize_language, normalize_proficiency, translate, SUPPORTED_LANGUAGES, SUPPORTED_PROFICIENCIES, label_for_proficiency, surf_call, classification_label
from .seed_data import DEFAULT_PARAMS
app=FastAPI(title='WaveWatch')
templates=Jinja2Templates(directory='app/templates')
app.mount('/static', StaticFiles(directory='app/static'), name='static')
scheduler=AsyncIOScheduler()
UPLOAD_DIR=Path('app/static/uploads')


def slugify(value: str) -> str:
    slug=re.sub(r'[^a-z0-9]+','-',value.lower()).strip('-')
    return slug or secrets.token_hex(3)


def split_urls(value: str | None) -> list[str]:
    if not value: return []
    return [u.strip() for u in re.split(r'[\n,]+', value) if u.strip()]


def save_uploads(files: list[UploadFile] | None, prefix: str) -> list[str]:
    saved=[]; UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for f in files or []:
        if not f or not f.filename: continue
        suffix=Path(f.filename).suffix.lower()[:12]
        name=f"{slugify(prefix)}-{secrets.token_hex(6)}{suffix}"
        dest=UPLOAD_DIR/name
        content=f.file.read()
        if not content: continue
        dest.write_bytes(content)
        saved.append(f"/static/uploads/{name}")
    return saved


def default_language_for_user(user):
    if user and user.username_lower in {'loliking','david'}:
        return 'de'
    return 'en'

def prefs(request: Request, user=None):
    lang=normalize_language(request.cookies.get('ww_lang') or request.query_params.get('lang') or default_language_for_user(user))
    proficiency=normalize_proficiency(request.cookies.get('ww_proficiency') or request.query_params.get('proficiency') or 'advanced')
    def t(key): return translate(lang,key)
    def prof_label(value): return label_for_proficiency(value, lang)
    return {'lang':lang,'proficiency':proficiency,'t':t,'languages':SUPPORTED_LANGUAGES,'proficiencies':list(SUPPORTED_PROFICIENCIES.keys()),'prof_label':prof_label,'surf_call':lambda score, confidence: surf_call(score, confidence, lang),'classification_label':lambda v: classification_label(v, lang)}


def webcam_links_for_spot(spot: SurfSpot) -> list[dict[str, str]]:
    links = []
    if spot.webcam_url:
        links.append({'label': 'Windy webcams', 'url': spot.webcam_url, 'source': 'Windy'})
    if spot.slug == 'odeceixe':
        links.append({'label': 'Odeceixe live webcam', 'url': 'https://beachcam.meo.pt/livecams/odeceixe', 'source': 'Beachcam MEO'})
    return links

@app.get('/preferences')
def set_preferences(request:Request, lang:str='en', proficiency:str='advanced', next:str='/surf'):
    lang=normalize_language(lang); proficiency=normalize_proficiency(proficiency)
    if not next.startswith('/') or next.startswith('//'): next='/surf'
    resp=RedirectResponse(next, status_code=303)
    resp.set_cookie('ww_lang', lang, httponly=False, samesite='lax')
    resp.set_cookie('ww_proficiency', proficiency, httponly=False, samesite='lax')
    return resp

def current_user(request:Request, db:OrmSession=Depends(get_db)):
    s=get_session(db, request.cookies.get('ww_session'))
    if not s: return None
    return s.user
def require_user(request:Request, db:OrmSession=Depends(get_db)):
    s=get_session(db, request.cookies.get('ww_session'))
    if not s: raise HTTPException(status_code=303, headers={'Location':'/login'})
    request.state.csrf=s.csrf_token
    if request.url.path not in {'/health'} and not request.url.path.startswith('/static'):
        db.add(PageAccess(user_id=s.user_id, accessed_at=datetime.now(UTC), method=request.method, path=request.url.path, user_agent=request.headers.get('user-agent')))
        db.commit()
    return s.user

def require_admin(request:Request, user=Depends(require_user)):
    if user.role != 'admin': raise HTTPException(404)
    return user
@app.on_event('startup')
async def startup():
    Base.metadata.create_all(engine); seed()
    db=SessionLocal();
    try: await ensure_seed_forecasts(db)
    finally: db.close()
    async def refresh():
        db=SessionLocal()
        try: await ensure_seed_forecasts(db); calculate_recommendations(db)
        finally: db.close()
    if not scheduler.running:
        scheduler.add_job(refresh,'interval',minutes=60,id='forecast-refresh',replace_existing=True); scheduler.start()
@app.get('/', response_class=HTMLResponse)
def home(request:Request, user=Depends(current_user)):
    if user: return RedirectResponse('/surf', status_code=303)
    return templates.TemplateResponse('login.html', {'request':request,'csrf':'anonymous','error':None,'page_title':'Login', **prefs(request)})
@app.get('/login', response_class=HTMLResponse)
def login_form(request:Request, user=Depends(current_user)):
    if user: return RedirectResponse('/surf', status_code=303)
    return templates.TemplateResponse('login.html', {'request':request,'csrf':'anonymous','error':None,'page_title':'Login', **prefs(request)})
@app.post('/login')
def login(request:Request, username:str=Form(...), password:str=Form(...), db:OrmSession=Depends(get_db)):
    key=(request.client.host if request.client else 'local')+':'+username.lower()
    if rate_limited(key): return templates.TemplateResponse('login.html', {'request':request,'csrf':'anonymous','error':translate(prefs(request)['lang'],'invalid_credentials'),'page_title':'Login', **prefs(request)}, status_code=429)
    user=db.query(User).filter(User.username_lower==username.lower()).first()
    if not user or not verify_password(password,user.password_hash):
        record_failure(key); return templates.TemplateResponse('login.html', {'request':request,'csrf':'anonymous','error':translate(prefs(request)['lang'],'invalid_credentials'),'page_title':'Login', **prefs(request)}, status_code=401)
    old=request.cookies.get('ww_session'); destroy_session(db, old); s=create_session(db,user,old); clear_failures(key)
    db.add(LoginEvent(user_id=user.id, logged_in_at=datetime.now(UTC), ip_address=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'))); db.commit()
    resp=RedirectResponse('/surf',status_code=303); set_session_cookie(resp,s.id); return resp
@app.get('/logout')
def logout_link(request:Request, db:OrmSession=Depends(get_db)):
    sid=request.cookies.get('ww_session'); destroy_session(db,sid)
    resp=RedirectResponse('/login',status_code=303); clear_session_cookie(resp); return resp
@app.post('/logout')
def logout(request:Request, csrf_token:str=Form(...), db:OrmSession=Depends(get_db)):
    sid=request.cookies.get('ww_session'); s=get_session(db,sid)
    if s and csrf_token!=s.csrf_token: raise HTTPException(403)
    destroy_session(db,sid); resp=RedirectResponse('/login',status_code=303); clear_session_cookie(resp); return resp
@app.get('/surf', response_class=HTMLResponse)
def surf(request:Request, user=Depends(require_user), db:OrmSession=Depends(get_db)):
    pref=prefs(request, user); date=datetime.now(ZoneInfo(settings.timezone)).date(); rankings=calculate_rankings(db, date, pref['proficiency'])
    by={part:(rows[0] if rows else None) for part, rows in rankings.items()}
    alternatives={part:rows[1:3] for part, rows in rankings.items()}
    spots=db.query(SurfSpot).order_by(SurfSpot.name).all(); latest=db.query(MarineForecast).order_by(desc(MarineForecast.fetched_at)).first()
    spot_summaries={}
    for s in spots:
        candidates=[r for rows in rankings.values() for r in rows if r.spot_id==s.id]
        spot_summaries[s.id]=max(candidates, key=lambda r:r.score) if candidates else None
    return templates.TemplateResponse('surf.html', {'request':request,'user':user,'date':date,'recommendations':by,'alternatives':alternatives,'spots':spots,'spot_summaries':spot_summaries,'csrf':request.state.csrf,'provider_status':provider_status(db),'newest_data':latest.fetched_at if latest else None, **pref})
@app.get('/surf/spots/{slug}', response_class=HTMLResponse)
def spot_detail(slug:str, request:Request, user=Depends(require_user), db:OrmSession=Depends(get_db)):
    pref=prefs(request, user); spot=db.query(SurfSpot).filter(SurfSpot.slug==slug).first()
    if not spot: raise HTTPException(404)
    date=datetime.now(ZoneInfo(settings.timezone)).date(); by=spot_daypart_scores(db, spot, date, pref['proficiency'])
    latest=db.query(MarineForecast).filter(MarineForecast.spot_id==spot.id).order_by(desc(MarineForecast.fetched_at)).first()
    return templates.TemplateResponse('spot_detail.html', {'request':request,'user':user,'spot':spot,'scores':by,'csrf':request.state.csrf,'provider_status':provider_status(db),'latest':latest,'osm_url':osm_link(spot.latitude, spot.longitude),'webcam_links':webcam_links_for_spot(spot), **pref})


def admin_context(db: OrmSession):
    users=db.query(User).order_by(User.username).all()
    login_events=db.query(LoginEvent).order_by(desc(LoginEvent.logged_in_at)).limit(5).all()
    accesses={}
    for u in users:
        rows=db.query(PageAccess).filter(PageAccess.user_id==u.id).order_by(desc(PageAccess.accessed_at)).limit(20).all()
        grouped=[]; current_day=None; current=[]
        for row in rows:
            day=row.accessed_at.date().isoformat()
            if day != current_day:
                if current: grouped.append({'day': current_day, 'rows': current})
                current_day=day; current=[]
            current.append(row)
        if current: grouped.append({'day': current_day, 'rows': current})
        accesses[u.id]=grouped
    beaches=db.query(Beach).order_by(Beach.name).all()
    spots=db.query(SurfSpot).order_by(SurfSpot.name).all()
    media=db.query(MediaAsset).order_by(desc(MediaAsset.created_at)).limit(40).all()
    webcam_links=db.query(WebcamLink).order_by(desc(WebcamLink.created_at)).limit(80).all()
    return {'users':users,'login_events':login_events,'accesses':accesses,'beaches':beaches,'spots':spots,'media':media,'webcam_links':webcam_links}


@app.get('/adm', response_class=HTMLResponse)
def admin_page(request:Request, user=Depends(require_admin), db:OrmSession=Depends(get_db)):
    return templates.TemplateResponse('admin.html', {'request':request,'user':user,'csrf':request.state.csrf, **admin_context(db), **prefs(request,user)})


@app.post('/adm/beaches')
def admin_add_beach(request:Request, name:str=Form(...), latitude:float=Form(...), longitude:float=Form(...), webcam_urls:str=Form(''), images:list[UploadFile]=File(default=[]), user=Depends(require_admin), db:OrmSession=Depends(get_db)):
    beach=Beach(name=name.strip(), latitude=latitude, longitude=longitude, image_paths=[], webcam_urls=split_urls(webcam_urls), created_at=datetime.now(UTC))
    db.add(beach); db.commit(); db.refresh(beach)
    paths=save_uploads(images, f'beach-{beach.id}-{name}')
    for path in paths: db.add(MediaAsset(entity_type='beach', entity_id=beach.id, path=path, original_filename=None, created_at=datetime.now(UTC)))
    for url in beach.webcam_urls or []: db.add(WebcamLink(entity_type='beach', entity_id=beach.id, url=url, label=beach.name, created_at=datetime.now(UTC)))
    beach.image_paths=paths; db.commit()
    return RedirectResponse('/adm', status_code=303)


@app.post('/adm/spots')
def admin_add_spot(request:Request, beach_id:int=Form(...), name:str=Form(...), latitude:float=Form(...), longitude:float=Form(...), webcam_urls:str=Form(''), images:list[UploadFile]=File(default=[]), user=Depends(require_admin), db:OrmSession=Depends(get_db)):
    beach=db.get(Beach, beach_id)
    if not beach: raise HTTPException(400, 'Unknown beach')
    base=DEFAULT_PARAMS.copy(); urls=split_urls(webcam_urls); slug=slugify(name)
    if db.query(SurfSpot).filter_by(slug=slug).first(): slug=f"{slug}-{secrets.token_hex(2)}"
    code=slugify(name)[:12].upper() or secrets.token_hex(3).upper()
    if db.query(SurfSpot).filter_by(code=code).first(): code=f"{code[:8]}{secrets.token_hex(2).upper()}"
    spot=SurfSpot(code=code, name=name.strip(), slug=slug, zone_name=beach.name, beach_name=beach.name, latitude=latitude, longitude=longitude, description='Added via admin page.', spot_type='Surf spot', difficulty='Unreviewed', is_active_for_recommendations=True, webcam_url=(urls[0] if urls else None), updated_at=datetime.now(UTC), **{k:v for k,v in base.items() if k not in {'webcam_url','seed_source_note'}})
    spot.seed_source_note='Added via /adm; provisional until reviewed.'
    db.add(spot); db.commit(); db.refresh(spot)
    for path in save_uploads(images, f'spot-{spot.id}-{name}'): db.add(MediaAsset(entity_type='surfspot', entity_id=spot.id, path=path, original_filename=None, created_at=datetime.now(UTC)))
    for url in urls: db.add(WebcamLink(entity_type='surfspot', entity_id=spot.id, url=url, label=spot.name, created_at=datetime.now(UTC)))
    db.commit(); return RedirectResponse('/adm', status_code=303)


@app.post('/adm/users')
def admin_add_user(request:Request, username:str=Form(...), temp_password:str=Form(...), user=Depends(require_admin), db:OrmSession=Depends(get_db)):
    uname=username.strip(); lower=uname.lower()
    if db.query(User).filter(User.username_lower==lower).first(): raise HTTPException(400, 'User already exists')
    db.add(User(username=uname, username_lower=lower, password_hash=hash_password(temp_password), role='user', created_at=datetime.now(UTC)))
    db.commit(); return RedirectResponse('/adm', status_code=303)

@app.get('/health')
def health(db:OrmSession=Depends(get_db)):
    try:
        users=db.query(User).count(); spots=db.query(SurfSpot).count(); dbok=True
    except Exception:
        users=spots=0; dbok=False
    return {'application':'WaveWatch','ok':dbok,'database':'healthy' if dbok else 'unavailable','users':users,'surf_spots':spots,'providers':provider_status(db)}
