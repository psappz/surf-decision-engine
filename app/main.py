from datetime import datetime, UTC
from zoneinfo import ZoneInfo
from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy import desc
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from .database import get_db, SessionLocal, engine
from .models import Base, User, SurfSpot, SpotScore, DailyRecommendation, MarineForecast, Session as DbSession
from .security import verify_password, rate_limited, record_failure, clear_failures, create_session, get_session, destroy_session, set_session_cookie, clear_session_cookie
from .seed import seed
from .forecast_service import ensure_seed_forecasts, calculate_recommendations, provider_status, calculate_rankings, spot_daypart_scores
from .config import settings
from .i18n import normalize_language, normalize_proficiency, translate, SUPPORTED_LANGUAGES, SUPPORTED_PROFICIENCIES, label_for_proficiency, surf_call, classification_label
app=FastAPI(title='WaveWatch')
templates=Jinja2Templates(directory='app/templates')
app.mount('/static', StaticFiles(directory='app/static'), name='static')
scheduler=AsyncIOScheduler()

def prefs(request: Request):
    lang=normalize_language(request.cookies.get('ww_lang') or request.query_params.get('lang') or 'en')
    proficiency=normalize_proficiency(request.cookies.get('ww_proficiency') or request.query_params.get('proficiency') or 'advanced')
    def t(key): return translate(lang,key)
    def prof_label(value): return label_for_proficiency(value, lang)
    return {'lang':lang,'proficiency':proficiency,'t':t,'languages':SUPPORTED_LANGUAGES,'proficiencies':list(SUPPORTED_PROFICIENCIES.keys()),'prof_label':prof_label,'surf_call':lambda score, confidence: surf_call(score, confidence, lang),'classification_label':lambda v: classification_label(v, lang)}

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
    return s.user
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
    return templates.TemplateResponse('login.html', {'request':request,'csrf':'anonymous','error':None, **prefs(request)})
@app.get('/login', response_class=HTMLResponse)
def login_form(request:Request, user=Depends(current_user)):
    if user: return RedirectResponse('/surf', status_code=303)
    return templates.TemplateResponse('login.html', {'request':request,'csrf':'anonymous','error':None, **prefs(request)})
@app.post('/login')
def login(request:Request, username:str=Form(...), password:str=Form(...), db:OrmSession=Depends(get_db)):
    key=(request.client.host if request.client else 'local')+':'+username.lower()
    if rate_limited(key): return templates.TemplateResponse('login.html', {'request':request,'csrf':'anonymous','error':translate(prefs(request)['lang'],'invalid_credentials'), **prefs(request)}, status_code=429)
    user=db.query(User).filter(User.username_lower==username.lower()).first()
    if not user or not verify_password(password,user.password_hash):
        record_failure(key); return templates.TemplateResponse('login.html', {'request':request,'csrf':'anonymous','error':translate(prefs(request)['lang'],'invalid_credentials'), **prefs(request)}, status_code=401)
    old=request.cookies.get('ww_session'); destroy_session(db, old); s=create_session(db,user,old); clear_failures(key)
    resp=RedirectResponse('/surf',status_code=303); set_session_cookie(resp,s.id); return resp
@app.post('/logout')
def logout(request:Request, csrf_token:str=Form(...), db:OrmSession=Depends(get_db)):
    sid=request.cookies.get('ww_session'); s=get_session(db,sid)
    if s and csrf_token!=s.csrf_token: raise HTTPException(403)
    destroy_session(db,sid); resp=RedirectResponse('/login',status_code=303); clear_session_cookie(resp); return resp
@app.get('/surf', response_class=HTMLResponse)
def surf(request:Request, user=Depends(require_user), db:OrmSession=Depends(get_db)):
    pref=prefs(request); date=datetime.now(ZoneInfo(settings.timezone)).date(); rankings=calculate_rankings(db, date, pref['proficiency'])
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
    pref=prefs(request); spot=db.query(SurfSpot).filter(SurfSpot.slug==slug).first()
    if not spot: raise HTTPException(404)
    date=datetime.now(ZoneInfo(settings.timezone)).date(); by=spot_daypart_scores(db, spot, date, pref['proficiency'])
    latest=db.query(MarineForecast).filter(MarineForecast.spot_id==spot.id).order_by(desc(MarineForecast.fetched_at)).first()
    return templates.TemplateResponse('spot_detail.html', {'request':request,'user':user,'spot':spot,'scores':by,'csrf':request.state.csrf,'provider_status':provider_status(db),'latest':latest, **pref})
@app.get('/health')
def health(db:OrmSession=Depends(get_db)):
    try:
        users=db.query(User).count(); spots=db.query(SurfSpot).count(); dbok=True
    except Exception:
        users=spots=0; dbok=False
    return {'application':'WaveWatch','ok':dbok,'database':'healthy' if dbok else 'unavailable','users':users,'surf_spots':spots,'providers':provider_status(db)}
