from datetime import datetime, UTC
from .database import SessionLocal, engine
from .models import Base, User, SurfSpot
from .security import hash_password
from .seed_data import USERS, SPOTS, DEFAULT_PARAMS

def _apply_access_map_fields(spot):
    # Static access-map sketches are intentionally disabled for the POC.
    # Keep external navigation links only; the map feature can be reintroduced
    # later when curated/budgeted map material is available.
    spot.access_map_id = None
    spot.access_map_asset = None
    spot.access_map_status = 'missing'
    spot.external_navigation_url = spot.maps_url


def _windy_webcam_url(spot):
    # Do not server-fetch Windy. Store only a click-through map/webcam URL so
    # the private local app does not leak page views unless the user opens it.
    lat = f"{float(spot.latitude):.3f}"
    lon = f"{float(spot.longitude):.3f}"
    return f"https://www.windy.com/{lat}/{lon}?{lat},{lon},13"


def _apply_webcam_fields(spot):
    spot.webcam_url = _windy_webcam_url(spot)


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
                _apply_webcam_fields(existing)
                continue
            data=DEFAULT_PARAMS.copy(); data.update(s); data['is_active_for_recommendations']=data.pop('active'); data['updated_at']=datetime.now(UTC)
            spot = SurfSpot(**data)
            _apply_access_map_fields(spot)
            _apply_webcam_fields(spot)
            db.add(spot)
        db.commit()
    finally: db.close()
if __name__=='__main__': seed()
