from datetime import datetime, UTC
from zoneinfo import ZoneInfo
from pathlib import Path
import re, secrets
from fastapi import FastAPI, Request, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy import desc
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from .database import get_db, SessionLocal, engine
from .models import Base, User, SurfSpot, SpotScore, DailyRecommendation, MarineForecast, Session as DbSession, Beach, LoginEvent, PageAccess, MediaAsset, WebcamLink, SpotWebcam, WebcamSuggestion, SpotPhoto, UserFavoriteSpot
from .security import verify_password, hash_password, rate_limited, record_failure, clear_failures, create_session, get_session, destroy_session, set_session_cookie, clear_session_cookie
from .seed import seed
from .forecast_service import ensure_seed_forecasts, calculate_recommendations, provider_status, calculate_rankings, spot_daypart_scores
from .access_maps import osm_link
from .config import settings
from .i18n import normalize_language, normalize_proficiency, translate, SUPPORTED_LANGUAGES, SUPPORTED_PROFICIENCIES, label_for_proficiency, surf_call, classification_label
from .seed_data import DEFAULT_PARAMS
from .media import csrf_or_403, validate_slug, validate_webcam_url, process_spot_photo, media_response_path
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


def client_ip(request: Request) -> str:
    forwarded_for = request.headers.get('x-forwarded-for')
    if forwarded_for:
        first = forwarded_for.split(',', 1)[0].strip()
        if first:
            return first
    real_ip = request.headers.get('x-real-ip')
    if real_ip and real_ip.strip():
        return real_ip.strip()
    return request.client.host if request.client else 'local'


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

def require_moderator(request:Request, user=Depends(require_user)):
    if user.role not in {'admin','moderator'}: raise HTTPException(404)
    return user

MAX_FAVORITE_SPOTS = 5


def favorite_spot_ids(db: OrmSession, user_id: int) -> set[int]:
    return {row.spot_id for row in db.query(UserFavoriteSpot).filter_by(user_id=user_id).all()}


def favorite_context(db: OrmSession, user_id: int) -> dict:
    ids=favorite_spot_ids(db, user_id)
    return {'favorite_spot_ids':ids,'favorite_count':len(ids),'favorite_limit':MAX_FAVORITE_SPOTS,'favorite_limit_reached':len(ids) >= MAX_FAVORITE_SPOTS}

SPOT_EDIT_FIELDS = ['code','slug','name','beach_name','zone_name','latitude','longitude','description','spot_type','difficulty','is_active_for_recommendations','preferred_swell_direction_min','preferred_swell_direction_max','acceptable_swell_direction_min','acceptable_swell_direction_max','preferred_swell_height_min','preferred_swell_height_max','maximum_safe_swell_height_for_profile','preferred_period_min','preferred_period_max','preferred_wind_direction_min','preferred_wind_direction_max','preferred_tide_min','preferred_tide_max','tide_preference','exposure_factor','shelter_factor','hazards','access_notes','base_confidence','external_navigation_url','access_map_id','access_map_asset','access_map_status','seed_source_note']
FLOAT_FIELDS = {'latitude','longitude','preferred_swell_direction_min','preferred_swell_direction_max','acceptable_swell_direction_min','acceptable_swell_direction_max','preferred_swell_height_min','preferred_swell_height_max','maximum_safe_swell_height_for_profile','preferred_period_min','preferred_period_max','preferred_wind_direction_min','preferred_wind_direction_max','preferred_tide_min','preferred_tide_max','exposure_factor','shelter_factor','base_confidence'}
TEXT_FIELDS = set(SPOT_EDIT_FIELDS) - FLOAT_FIELDS - {'is_active_for_recommendations'}


def parse_spot_form(form, db: OrmSession, spot: SurfSpot):
    data={}; errors={}
    for field in TEXT_FIELDS:
        value=(form.get(field) or '').strip()
        data[field]=value or None
    data['is_active_for_recommendations']=form.get('is_active_for_recommendations') == 'on'
    for field in FLOAT_FIELDS:
        raw=(form.get(field) or '').strip()
        if raw == '': data[field]=None; continue
        try: data[field]=float(raw)
        except ValueError: errors[field]='Enter a number.'
    if not data.get('code'): errors['code']='Code is required.'
    if data.get('code') and db.query(SurfSpot).filter(SurfSpot.code==data['code'], SurfSpot.id!=spot.id).first(): errors['code']='Code already exists.'
    if not data.get('slug') or not validate_slug(data['slug']): errors['slug']='Use lowercase letters, numbers and hyphens.'
    if data.get('slug') and db.query(SurfSpot).filter(SurfSpot.slug==data['slug'], SurfSpot.id!=spot.id).first(): errors['slug']='Slug already exists.'
    if not data.get('name'): errors['name']='Name is required.'
    lat=data.get('latitude'); lon=data.get('longitude')
    if lat is None or not (-90 <= lat <= 90): errors['latitude']='Latitude must be between -90 and 90.'
    if lon is None or not (-180 <= lon <= 180): errors['longitude']='Longitude must be between -180 and 180.'
    for field in ['preferred_swell_direction_min','preferred_swell_direction_max','acceptable_swell_direction_min','acceptable_swell_direction_max','preferred_wind_direction_min','preferred_wind_direction_max']:
        val=data.get(field)
        if val is not None and not (0 <= val <= 360): errors[field]='Direction must be between 0 and 360; wraparound ranges are allowed.'
    return data, errors

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
    ip=client_ip(request)
    key=ip+':'+username.lower()
    if rate_limited(key): return templates.TemplateResponse('login.html', {'request':request,'csrf':'anonymous','error':translate(prefs(request)['lang'],'invalid_credentials'),'page_title':'Login', **prefs(request)}, status_code=429)
    user=db.query(User).filter(User.username_lower==username.lower()).first()
    if not user or not verify_password(password,user.password_hash):
        record_failure(key); return templates.TemplateResponse('login.html', {'request':request,'csrf':'anonymous','error':translate(prefs(request)['lang'],'invalid_credentials'),'page_title':'Login', **prefs(request)}, status_code=401)
    old=request.cookies.get('ww_session'); destroy_session(db, old); s=create_session(db,user,old); clear_failures(key)
    db.add(LoginEvent(user_id=user.id, logged_in_at=datetime.now(UTC), ip_address=ip, user_agent=request.headers.get('user-agent'))); db.commit()
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
    fav_ctx=favorite_context(db, user.id)
    spots=sorted(spots, key=lambda s: (s.id not in fav_ctx['favorite_spot_ids'], s.name.lower()))
    spot_summaries={}
    for s in spots:
        candidates=[r for rows in rankings.values() for r in rows if r.spot_id==s.id]
        spot_summaries[s.id]=max(candidates, key=lambda r:r.score) if candidates else None
    return templates.TemplateResponse('surf.html', {'request':request,'user':user,'date':date,'recommendations':by,'alternatives':alternatives,'spots':spots,'spot_summaries':spot_summaries,'csrf':request.state.csrf,'provider_status':provider_status(db),'newest_data':latest.fetched_at if latest else None, **fav_ctx, **pref})
@app.get('/surf/spots/{slug}', response_class=HTMLResponse)
def spot_detail(slug:str, request:Request, user=Depends(require_user), db:OrmSession=Depends(get_db)):
    pref=prefs(request, user); spot=db.query(SurfSpot).filter(SurfSpot.slug==slug).first()
    if not spot: raise HTTPException(404)
    date=datetime.now(ZoneInfo(settings.timezone)).date(); by=spot_daypart_scores(db, spot, date, pref['proficiency'])
    latest=db.query(MarineForecast).filter(MarineForecast.spot_id==spot.id).order_by(desc(MarineForecast.fetched_at)).first()
    webcams=db.query(SpotWebcam).filter_by(spot_id=spot.id, is_active=True).order_by(SpotWebcam.sort_order, SpotWebcam.id).all()
    photos=db.query(SpotPhoto).filter_by(spot_id=spot.id, status='active').order_by(desc(SpotPhoto.created_at)).all()
    is_favorite=db.query(UserFavoriteSpot).filter_by(user_id=user.id, spot_id=spot.id).first() is not None
    return templates.TemplateResponse('spot_detail.html', {'request':request,'user':user,'spot':spot,'scores':by,'csrf':request.state.csrf,'provider_status':provider_status(db),'latest':latest,'osm_url':osm_link(spot.latitude, spot.longitude),'approved_webcams':webcams,'photos':photos,'is_favorite':is_favorite, **favorite_context(db, user.id), **pref})


@app.post('/surf/spots/{slug}/favorite')
def toggle_favorite_spot(slug:str, request:Request, csrf_token:str=Form(...), favorite:str|None=Form(None), next:str=Form('/surf'), user=Depends(require_user), db:OrmSession=Depends(get_db)):
    csrf_or_403(request, csrf_token)
    spot=db.query(SurfSpot).filter_by(slug=slug).first()
    if not spot: raise HTTPException(404)
    existing=db.query(UserFavoriteSpot).filter_by(user_id=user.id, spot_id=spot.id).first()
    wants_favorite = favorite == 'on'
    if wants_favorite and not existing:
        count=db.query(UserFavoriteSpot).filter_by(user_id=user.id).count()
        if count >= MAX_FAVORITE_SPOTS:
            target=next if next.startswith('/') and not next.startswith('//') else '/surf'
            sep='&' if '?' in target else '?'
            return RedirectResponse(f'{target}{sep}favorite_limit=1', status_code=303)
        db.add(UserFavoriteSpot(user_id=user.id, spot_id=spot.id, created_at=datetime.now(UTC)))
        db.commit()
    elif not wants_favorite and existing:
        db.delete(existing); db.commit()
    target=next if next.startswith('/') and not next.startswith('//') else '/surf'
    return RedirectResponse(target, status_code=303)


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
    spot_rows=[]
    for spot in spots:
        spot_rows.append({'spot':spot,'webcam_count':db.query(SpotWebcam).filter_by(spot_id=spot.id, is_active=True).count(),'photo_count':db.query(SpotPhoto).filter_by(spot_id=spot.id, status='active').count()})
    return {'users':users,'login_events':login_events,'accesses':accesses,'beaches':beaches,'spots':spots,'spot_rows':spot_rows,'media':media,'webcam_links':webcam_links}


@app.get('/adm', response_class=HTMLResponse)
def admin_page(request:Request, user=Depends(require_admin), db:OrmSession=Depends(get_db)):
    return templates.TemplateResponse('admin.html', {'request':request,'user':user,'csrf':request.state.csrf, **admin_context(db), **prefs(request,user)})


@app.get('/adm/spots/{spot_id}', response_class=HTMLResponse)
def admin_edit_spot(spot_id:int, request:Request, user=Depends(require_admin), db:OrmSession=Depends(get_db)):
    spot=db.get(SurfSpot, spot_id)
    if not spot: raise HTTPException(404)
    webcams=db.query(SpotWebcam).filter_by(spot_id=spot.id).order_by(SpotWebcam.sort_order, SpotWebcam.id).all()
    photos=db.query(SpotPhoto).filter_by(spot_id=spot.id).order_by(desc(SpotPhoto.created_at)).all()
    return templates.TemplateResponse('admin_spot_edit.html', {'request':request,'user':user,'spot':spot,'fields':SPOT_EDIT_FIELDS,'float_fields':FLOAT_FIELDS,'webcams':webcams,'photos':photos,'errors':{},'csrf':request.state.csrf, **prefs(request,user)})


@app.post('/adm/spots/{spot_id}', response_class=HTMLResponse)
async def admin_update_spot(spot_id:int, request:Request, user=Depends(require_admin), db:OrmSession=Depends(get_db)):
    spot=db.get(SurfSpot, spot_id)
    if not spot: raise HTTPException(404)
    form=await request.form(); csrf_or_403(request, form.get('csrf_token'))
    data, errors=parse_spot_form(form, db, spot)
    if errors:
        webcams=db.query(SpotWebcam).filter_by(spot_id=spot.id).order_by(SpotWebcam.sort_order, SpotWebcam.id).all()
        photos=db.query(SpotPhoto).filter_by(spot_id=spot.id).order_by(desc(SpotPhoto.created_at)).all()
        return templates.TemplateResponse('admin_spot_edit.html', {'request':request,'user':user,'spot':spot,'fields':SPOT_EDIT_FIELDS,'float_fields':FLOAT_FIELDS,'webcams':webcams,'photos':photos,'errors':errors,'csrf':request.state.csrf, **prefs(request,user)}, status_code=400)
    for k,v in data.items(): setattr(spot,k,v)
    spot.updated_at=datetime.now(UTC)
    db.commit()
    return RedirectResponse(f'/adm/spots/{spot.id}?saved=1', status_code=303)


@app.post('/adm/spots/{spot_id}/webcams')
async def admin_add_webcam(spot_id:int, request:Request, user=Depends(require_admin), db:OrmSession=Depends(get_db)):
    spot=db.get(SurfSpot, spot_id)
    if not spot: raise HTTPException(404)
    form=await request.form(); csrf_or_403(request, form.get('csrf_token'))
    try: url=validate_webcam_url(str(form.get('url') or ''), allow_http=form.get('allow_http')=='on')
    except ValueError as exc: raise HTTPException(400, str(exc))
    now=datetime.now(UTC); max_order=db.query(SpotWebcam).filter_by(spot_id=spot_id).count()
    db.add(SpotWebcam(spot_id=spot_id,title=(form.get('title') or spot.name).strip(),operator_name=(form.get('operator_name') or 'Unknown operator').strip(),url=url,description=(form.get('description') or '').strip() or None,is_active=form.get('is_active')=='on',sort_order=max_order,created_at=now,updated_at=now,created_by_user_id=user.id,approved_source_type=form.get('approved_source_type') or 'operator'))
    db.commit(); return RedirectResponse(f'/adm/spots/{spot_id}#webcams', status_code=303)


@app.post('/adm/webcams/{webcam_id}/update')
async def admin_update_webcam(webcam_id:int, request:Request, user=Depends(require_admin), db:OrmSession=Depends(get_db)):
    webcam=db.get(SpotWebcam, webcam_id)
    if not webcam: raise HTTPException(404)
    form=await request.form(); csrf_or_403(request, form.get('csrf_token'))
    try: webcam.url=validate_webcam_url(str(form.get('url') or ''), allow_http=form.get('allow_http')=='on')
    except ValueError as exc: raise HTTPException(400, str(exc))
    webcam.title=(form.get('title') or webcam.title).strip(); webcam.operator_name=(form.get('operator_name') or webcam.operator_name).strip(); webcam.description=(form.get('description') or '').strip() or None; webcam.is_active=form.get('is_active')=='on'; webcam.sort_order=int(form.get('sort_order') or 0); webcam.approved_source_type=form.get('approved_source_type') or 'operator'; webcam.updated_at=datetime.now(UTC)
    db.commit(); return RedirectResponse(f'/adm/spots/{webcam.spot_id}#webcams', status_code=303)


@app.post('/adm/webcams/{webcam_id}/delete')
async def admin_delete_webcam(webcam_id:int, request:Request, user=Depends(require_admin), db:OrmSession=Depends(get_db)):
    webcam=db.get(SpotWebcam, webcam_id)
    if not webcam: raise HTTPException(404)
    form=await request.form(); csrf_or_403(request, form.get('csrf_token'))
    spot_id=webcam.spot_id; db.delete(webcam); db.commit(); return RedirectResponse(f'/adm/spots/{spot_id}#webcams', status_code=303)


@app.post('/adm/spots/{spot_id}/webcams/reorder')
async def admin_reorder_webcams(spot_id:int, request:Request, user=Depends(require_admin), db:OrmSession=Depends(get_db)):
    form=await request.form(); csrf_or_403(request, form.get('csrf_token'))
    ids=[int(x) for x in str(form.get('ordered_ids') or '').replace('\n', ',').split(',') if x.strip().isdigit()]
    for idx, wid in enumerate(ids):
        w=db.get(SpotWebcam, wid)
        if w and w.spot_id==spot_id: w.sort_order=idx; w.updated_at=datetime.now(UTC)
    db.commit(); return RedirectResponse(f'/adm/spots/{spot_id}#webcams', status_code=303)


@app.get('/mod', response_class=HTMLResponse)
def mod_page(request:Request, user=Depends(require_moderator), db:OrmSession=Depends(get_db)):
    pending=db.query(WebcamSuggestion).filter_by(status='pending').order_by(WebcamSuggestion.submitted_at).all()
    photos=db.query(SpotPhoto).filter(SpotPhoto.status!='deleted').order_by(desc(SpotPhoto.created_at)).limit(40).all()
    return templates.TemplateResponse('mod.html', {'request':request,'user':user,'suggestions':pending,'photos':photos,'csrf':request.state.csrf, **prefs(request,user)})

@app.get('/mod/webcam-suggestions', response_class=HTMLResponse)
def mod_webcam_suggestions(request:Request, user=Depends(require_moderator), db:OrmSession=Depends(get_db)):
    return mod_page(request,user,db)


@app.post('/mod/webcam-suggestions/{suggestion_id}/approve')
async def mod_approve_suggestion(suggestion_id:int, request:Request, user=Depends(require_moderator), db:OrmSession=Depends(get_db)):
    sug=db.get(WebcamSuggestion, suggestion_id)
    if not sug: raise HTTPException(404)
    form=await request.form(); csrf_or_403(request, form.get('csrf_token'))
    if sug.status=='approved' and sug.approved_webcam_id:
        return RedirectResponse('/mod', status_code=303)
    if sug.submitted_by_user_id==user.id and user.role!='admin': raise HTTPException(403, 'Users cannot approve their own suggestions')
    try: url=validate_webcam_url(str(form.get('url') or sug.suggested_url), allow_http=form.get('allow_http')=='on')
    except ValueError as exc: raise HTTPException(400, str(exc))
    now=datetime.now(UTC)
    existing=db.query(SpotWebcam).filter_by(spot_id=sug.spot_id,url=url).first()
    webcam=existing or SpotWebcam(spot_id=sug.spot_id,title=(form.get('title') or sug.suggested_title).strip(),operator_name=(form.get('operator_name') or sug.suggested_operator_name).strip(),url=url,description=(form.get('description') or sug.submitter_note or '').strip() or None,is_active=True,sort_order=db.query(SpotWebcam).filter_by(spot_id=sug.spot_id).count(),created_at=now,updated_at=now,created_by_user_id=user.id,approved_source_type=form.get('approved_source_type') or 'operator')
    if not existing: db.add(webcam); db.flush()
    sug.status='approved'; sug.reviewed_by_user_id=user.id; sug.reviewed_at=now; sug.moderator_note=(form.get('moderator_note') or '').strip() or None; sug.approved_webcam_id=webcam.id
    db.commit(); return RedirectResponse('/mod', status_code=303)


@app.post('/mod/webcam-suggestions/{suggestion_id}/reject')
async def mod_reject_suggestion(suggestion_id:int, request:Request, user=Depends(require_moderator), db:OrmSession=Depends(get_db)):
    sug=db.get(WebcamSuggestion, suggestion_id)
    if not sug: raise HTTPException(404)
    form=await request.form(); csrf_or_403(request, form.get('csrf_token'))
    sug.status='rejected'; sug.reviewed_by_user_id=user.id; sug.reviewed_at=datetime.now(UTC); sug.moderator_note=(form.get('moderator_note') or '').strip() or None
    db.commit(); return RedirectResponse('/mod', status_code=303)


@app.post('/mod/photos/{photo_id}/status')
async def mod_photo_status(photo_id:int, request:Request, user=Depends(require_moderator), db:OrmSession=Depends(get_db)):
    photo=db.get(SpotPhoto, photo_id)
    if not photo: raise HTTPException(404)
    form=await request.form(); csrf_or_403(request, form.get('csrf_token'))
    if form.get('status') in {'active','hidden'}: photo.status=form.get('status'); photo.updated_at=datetime.now(UTC); db.commit()
    return RedirectResponse('/mod', status_code=303)


@app.post('/surf/spots/{slug}/webcam-suggestions')
async def suggest_webcam(slug:str, request:Request, user=Depends(require_user), db:OrmSession=Depends(get_db)):
    spot=db.query(SurfSpot).filter_by(slug=slug).first()
    if not spot: raise HTTPException(404)
    form=await request.form(); csrf_or_403(request, form.get('csrf_token'))
    try: url=validate_webcam_url(str(form.get('suggested_url') or ''))
    except ValueError as exc: raise HTTPException(400, str(exc))
    if db.query(WebcamSuggestion).filter_by(spot_id=spot.id,suggested_url=url,status='pending').first(): raise HTTPException(400, 'This webcam suggestion is already pending review.')
    db.add(WebcamSuggestion(spot_id=spot.id,submitted_by_user_id=user.id,suggested_url=url,suggested_title=(form.get('suggested_title') or spot.name).strip(),suggested_operator_name=(form.get('suggested_operator_name') or 'Unknown operator').strip(),submitter_note=(form.get('submitter_note') or '').strip() or None,status='pending',submitted_at=datetime.now(UTC)))
    db.commit(); return RedirectResponse(f'/surf/spots/{spot.slug}?suggested=1#webcams', status_code=303)


@app.post('/surf/spots/{slug}/photos')
async def upload_spot_photos(slug:str, request:Request, caption:str=Form(''), csrf_token:str=Form(...), images:list[UploadFile]=File(default=[]), user=Depends(require_user), db:OrmSession=Depends(get_db)):
    csrf_or_403(request, csrf_token)
    spot=db.query(SurfSpot).filter_by(slug=slug).first()
    if not spot: raise HTTPException(404)
    if not images or len(images) > settings.max_upload_files: raise HTTPException(400, f'Upload 1 to {settings.max_upload_files} images.')
    total_size=sum((getattr(img, 'size', 0) or 0) for img in images)
    if total_size and total_size > settings.max_upload_total_mb*1024*1024: raise HTTPException(400, 'Upload request exceeds the configured total size limit.')
    now=datetime.now(UTC); max_bytes=settings.max_upload_file_mb*1024*1024
    for img in images:
        try:
            processed=await process_spot_photo(img, spot.id, max_file_bytes=max_bytes)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        db.add(SpotPhoto(spot_id=spot.id,uploaded_by_user_id=user.id,display_path=processed.display_rel,thumbnail_path=processed.thumbnail_rel,original_filename=Path(img.filename or '').name[:255],stored_mime_type=processed.stored_mime_type,width=processed.width,height=processed.height,file_size=processed.file_size,caption=caption.strip() or None,status='active',created_at=now,updated_at=now))
    db.commit(); return RedirectResponse(f'/surf/spots/{spot.slug}?uploaded=1#photos', status_code=303)


@app.get('/media/{path:path}')
def media_file(path:str):
    target=media_response_path(path)
    return FileResponse(target, media_type='image/webp', headers={'X-Content-Type-Options':'nosniff'})


@app.post('/adm/beaches')
def admin_add_beach(request:Request, name:str=Form(...), latitude:float=Form(...), longitude:float=Form(...), webcam_urls:str=Form(''), csrf_token:str=Form(...), images:list[UploadFile]=File(default=[]), user=Depends(require_admin), db:OrmSession=Depends(get_db)):
    csrf_or_403(request, csrf_token)
    beach=Beach(name=name.strip(), latitude=latitude, longitude=longitude, image_paths=[], webcam_urls=split_urls(webcam_urls), created_at=datetime.now(UTC))
    db.add(beach); db.commit(); db.refresh(beach)
    paths=save_uploads(images, f'beach-{beach.id}-{name}')
    for path in paths: db.add(MediaAsset(entity_type='beach', entity_id=beach.id, path=path, original_filename=None, created_at=datetime.now(UTC)))
    for url in beach.webcam_urls or []: db.add(WebcamLink(entity_type='beach', entity_id=beach.id, url=url, label=beach.name, created_at=datetime.now(UTC)))
    beach.image_paths=paths; db.commit()
    return RedirectResponse('/adm', status_code=303)


@app.post('/adm/spots')
def admin_add_spot(request:Request, beach_id:int=Form(...), name:str=Form(...), latitude:float=Form(...), longitude:float=Form(...), webcam_urls:str=Form(''), csrf_token:str=Form(...), images:list[UploadFile]=File(default=[]), user=Depends(require_admin), db:OrmSession=Depends(get_db)):
    csrf_or_403(request, csrf_token)
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
def admin_add_user(request:Request, username:str=Form(...), temp_password:str=Form(...), csrf_token:str=Form(...), user=Depends(require_admin), db:OrmSession=Depends(get_db)):
    csrf_or_403(request, csrf_token)
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
