from datetime import datetime, UTC
from .database import SessionLocal, engine
from .models import Base, User, SurfSpot
from .security import hash_password
from .seed_data import USERS, SPOTS, DEFAULT_PARAMS
from .access_maps import spot_to_access_map

def _apply_access_map_fields(spot):
    access_cfg = spot_to_access_map().get(spot.slug)
    if not access_cfg:
        spot.access_map_id = None
        spot.access_map_asset = None
        spot.access_map_status = 'missing'
        spot.external_navigation_url = spot.maps_url
        return
    spot.access_map_id = access_cfg.id
    spot.access_map_asset = f'/static/access-maps/{access_cfg.id}.svg'
    spot.access_map_status = 'missing'
    spot.external_navigation_url = spot.maps_url

def seed():
    Base.metadata.create_all(engine)
    db=SessionLocal()
    try:
        for username,password,role in USERS:
            if not db.query(User).filter(User.username_lower==username.lower()).first():
                db.add(User(username=username, username_lower=username.lower(), password_hash=hash_password(password), role=role, created_at=datetime.now(UTC)))
        for s in SPOTS:
            existing = db.query(SurfSpot).filter(SurfSpot.slug==s['slug']).first()
            if existing:
                _apply_access_map_fields(existing)
                continue
            data=DEFAULT_PARAMS.copy(); data.update(s); data['is_active_for_recommendations']=data.pop('active'); data['updated_at']=datetime.now(UTC)
            spot = SurfSpot(**data)
            _apply_access_map_fields(spot)
            db.add(spot)
        db.commit()
    finally: db.close()
if __name__=='__main__': seed()
