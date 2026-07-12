from datetime import datetime, UTC
from .database import SessionLocal, engine
from .models import Base, User, SurfSpot
from .security import hash_password
from .seed_data import USERS, SPOTS, DEFAULT_PARAMS
def seed():
    Base.metadata.create_all(engine)
    db=SessionLocal()
    try:
        for username,password,role in USERS:
            if not db.query(User).filter(User.username_lower==username.lower()).first():
                db.add(User(username=username, username_lower=username.lower(), password_hash=hash_password(password), role=role, created_at=datetime.now(UTC)))
        for s in SPOTS:
            if db.query(SurfSpot).filter(SurfSpot.slug==s['slug']).first(): continue
            data=DEFAULT_PARAMS.copy(); data.update(s); data['is_active_for_recommendations']=data.pop('active'); data['updated_at']=datetime.now(UTC)
            db.add(SurfSpot(**data))
        db.commit()
    finally: db.close()
if __name__=='__main__': seed()
