import secrets, time
from datetime import datetime, timedelta, UTC
from passlib.context import CryptContext
from sqlalchemy.orm import Session as OrmSession
from .models import User, Session
from .config import settings
pwd_context=CryptContext(schemes=["bcrypt"], deprecated="auto")
_login_attempts: dict[str,list[float]]={}
def hash_password(p:str)->str: return pwd_context.hash(p)
def verify_password(p:str,h:str)->bool: return pwd_context.verify(p,h)
def rate_limited(key:str, limit:int=6, window:int=300)->bool:
    now=time.time(); bucket=[t for t in _login_attempts.get(key,[]) if now-t<window]; _login_attempts[key]=bucket
    return len(bucket)>=limit
def record_failure(key:str): _login_attempts.setdefault(key,[]).append(time.time())
def clear_failures(key:str): _login_attempts.pop(key,None)
def create_session(db:OrmSession, user:User, rotated_from:str|None=None)->Session:
    s=Session(id=secrets.token_urlsafe(32), user_id=user.id, csrf_token=secrets.token_urlsafe(32), created_at=datetime.now(UTC), expires_at=datetime.now(UTC)+timedelta(days=7), rotated_from=rotated_from)
    db.add(s); db.commit(); db.refresh(s); return s
def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
def get_session(db:OrmSession, sid:str|None)->Session|None:
    if not sid: return None
    s=db.get(Session, sid)
    if not s or _aware(s.expires_at) < datetime.now(UTC): return None
    return s
def destroy_session(db:OrmSession, sid:str|None):
    if sid and (s:=db.get(Session,sid)):
        db.delete(s); db.commit()
def set_session_cookie(response, sid):
    response.set_cookie('ww_session', sid, httponly=True, samesite='lax', secure=settings.secure_cookies, max_age=7*86400)
def clear_session_cookie(response): response.delete_cookie('ww_session')
