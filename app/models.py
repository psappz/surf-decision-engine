from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, Float, Boolean, Text, DateTime, Date, ForeignKey, JSON, BigInteger, UniqueConstraint
from datetime import datetime
class Base(DeclarativeBase): pass
class User(Base):
    __tablename__='users'; id:Mapped[int]=mapped_column(primary_key=True); username:Mapped[str]=mapped_column(String(80),unique=True); username_lower:Mapped[str]=mapped_column(String(80),unique=True,index=True); password_hash:Mapped[str]=mapped_column(String(255)); role:Mapped[str]=mapped_column(String(30)); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
class Session(Base):
    __tablename__='sessions'; id:Mapped[str]=mapped_column(String(64),primary_key=True); user_id:Mapped[int]=mapped_column(ForeignKey('users.id'),index=True); csrf_token:Mapped[str]=mapped_column(String(64)); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True)); expires_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True); rotated_from:Mapped[str|None]=mapped_column(String(64),nullable=True); user=relationship('User')
class SurfSpot(Base):
    __tablename__='surf_spots'; id:Mapped[int]=mapped_column(primary_key=True); code:Mapped[str]=mapped_column(String(20),unique=True); slug:Mapped[str]=mapped_column(String(120),unique=True,index=True); name:Mapped[str]=mapped_column(String(120)); beach_name:Mapped[str|None]=mapped_column(String(120)); zone_name:Mapped[str|None]=mapped_column(String(160)); latitude:Mapped[float]=mapped_column(Float); longitude:Mapped[float]=mapped_column(Float); description:Mapped[str|None]=mapped_column(Text); spot_type:Mapped[str|None]=mapped_column(String(120)); difficulty:Mapped[str|None]=mapped_column(String(160)); is_active_for_recommendations:Mapped[bool]=mapped_column(Boolean); preferred_swell_direction_min:Mapped[float|None]=mapped_column(Float); preferred_swell_direction_max:Mapped[float|None]=mapped_column(Float); acceptable_swell_direction_min:Mapped[float|None]=mapped_column(Float); acceptable_swell_direction_max:Mapped[float|None]=mapped_column(Float); preferred_swell_height_min:Mapped[float|None]=mapped_column(Float); preferred_swell_height_max:Mapped[float|None]=mapped_column(Float); maximum_safe_swell_height_for_profile:Mapped[float|None]=mapped_column(Float); preferred_period_min:Mapped[float|None]=mapped_column(Float); preferred_period_max:Mapped[float|None]=mapped_column(Float); preferred_wind_direction_min:Mapped[float|None]=mapped_column(Float); preferred_wind_direction_max:Mapped[float|None]=mapped_column(Float); preferred_tide_min:Mapped[float|None]=mapped_column(Float); preferred_tide_max:Mapped[float|None]=mapped_column(Float); tide_preference:Mapped[str|None]=mapped_column(String(80)); exposure_factor:Mapped[float|None]=mapped_column(Float); shelter_factor:Mapped[float|None]=mapped_column(Float); hazards:Mapped[str|None]=mapped_column(Text); access_notes:Mapped[str|None]=mapped_column(Text); base_confidence:Mapped[float|None]=mapped_column(Float); webcam_url:Mapped[str|None]=mapped_column(String(500)); seed_source_note:Mapped[str|None]=mapped_column(Text); access_map_asset:Mapped[str|None]=mapped_column(String(255),nullable=True); access_map_id:Mapped[str|None]=mapped_column(String(120),nullable=True,index=True); external_navigation_url:Mapped[str|None]=mapped_column(String(500),nullable=True); access_map_status:Mapped[str]=mapped_column(String(30),default='missing'); updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    @property
    def maps_url(self): return f"https://www.google.com/maps/search/?api=1&query={self.latitude},{self.longitude}"
class ProviderFetch(Base):
    __tablename__='provider_fetches'; id:Mapped[int]=mapped_column(primary_key=True); provider_name:Mapped[str]=mapped_column(String(100),index=True); fetched_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True); latitude:Mapped[float|None]=mapped_column(Float); longitude:Mapped[float|None]=mapped_column(Float); status:Mapped[str]=mapped_column(String(30)); raw_response:Mapped[dict|None]=mapped_column(JSON); parsing_errors:Mapped[str|None]=mapped_column(Text); data_age_seconds:Mapped[int|None]=mapped_column(Integer)
class MarineForecast(Base):
    __tablename__='marine_forecasts'; id:Mapped[int]=mapped_column(primary_key=True); provider_fetch_id:Mapped[int|None]=mapped_column(ForeignKey('provider_fetches.id')); provider_name:Mapped[str|None]=mapped_column(String(100),index=True); spot_id:Mapped[int|None]=mapped_column(ForeignKey('surf_spots.id'),index=True); forecast_time:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True); fetched_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True); values:Mapped[dict]=mapped_column(JSON); provider_status:Mapped[str]=mapped_column(String(30))
class WeatherForecast(Base):
    __tablename__='weather_forecasts'; id:Mapped[int]=mapped_column(primary_key=True); provider_fetch_id:Mapped[int|None]=mapped_column(ForeignKey('provider_fetches.id')); provider_name:Mapped[str|None]=mapped_column(String(100),index=True); spot_id:Mapped[int|None]=mapped_column(ForeignKey('surf_spots.id'),index=True); forecast_time:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True); fetched_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True); values:Mapped[dict]=mapped_column(JSON); provider_status:Mapped[str]=mapped_column(String(30))
class TideForecast(Base):
    __tablename__='tide_forecasts'; id:Mapped[int]=mapped_column(primary_key=True); provider_fetch_id:Mapped[int|None]=mapped_column(ForeignKey('provider_fetches.id')); provider_name:Mapped[str|None]=mapped_column(String(100),index=True); spot_id:Mapped[int|None]=mapped_column(ForeignKey('surf_spots.id'),index=True); forecast_time:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True); fetched_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True); values:Mapped[dict]=mapped_column(JSON); provider_status:Mapped[str]=mapped_column(String(30))
class BuoyObservation(Base):
    __tablename__='buoy_observations'; id:Mapped[int]=mapped_column(primary_key=True); provider_name:Mapped[str|None]=mapped_column(String(100)); station_name:Mapped[str|None]=mapped_column(String(120)); observed_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True); values:Mapped[dict|None]=mapped_column(JSON); status:Mapped[str|None]=mapped_column(String(30))
class SpotScore(Base):
    __tablename__='spot_scores'; id:Mapped[int]=mapped_column(primary_key=True); spot_id:Mapped[int]=mapped_column(ForeignKey('surf_spots.id'),index=True); daypart:Mapped[str]=mapped_column(String(20),index=True); score_date:Mapped[object]=mapped_column(Date); score:Mapped[float]=mapped_column(Float); confidence_label:Mapped[str]=mapped_column(String(40)); classification:Mapped[str]=mapped_column(String(80)); explanation:Mapped[str|None]=mapped_column(Text); summary:Mapped[dict|None]=mapped_column(JSON); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True)); spot=relationship('SurfSpot')
class DailyRecommendation(Base):
    __tablename__='daily_recommendations'; id:Mapped[int]=mapped_column(primary_key=True); score_date:Mapped[object]=mapped_column(Date,index=True); daypart:Mapped[str]=mapped_column(String(20),index=True); spot_score_id:Mapped[int]=mapped_column(ForeignKey('spot_scores.id')); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True)); spot_score=relationship('SpotScore')
class Beach(Base):
    __tablename__='beaches'; id:Mapped[int]=mapped_column(primary_key=True); name:Mapped[str]=mapped_column(String(160),unique=True,index=True); latitude:Mapped[float]=mapped_column(Float); longitude:Mapped[float]=mapped_column(Float); image_paths:Mapped[list|None]=mapped_column(JSON,nullable=True); webcam_urls:Mapped[list|None]=mapped_column(JSON,nullable=True); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    @property
    def maps_url(self): return f"https://www.google.com/maps/search/?api=1&query={self.latitude},{self.longitude}"
class LoginEvent(Base):
    __tablename__='login_events'; id:Mapped[int]=mapped_column(primary_key=True); user_id:Mapped[int]=mapped_column(ForeignKey('users.id'),index=True); logged_in_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True); ip_address:Mapped[str|None]=mapped_column(String(80)); user_agent:Mapped[str|None]=mapped_column(Text); user=relationship('User')
class PageAccess(Base):
    __tablename__='page_accesses'; id:Mapped[int]=mapped_column(primary_key=True); user_id:Mapped[int]=mapped_column(ForeignKey('users.id'),index=True); accessed_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True); method:Mapped[str]=mapped_column(String(12)); path:Mapped[str]=mapped_column(String(500)); user_agent:Mapped[str|None]=mapped_column(Text); user=relationship('User')
class MediaAsset(Base):
    __tablename__='media_assets'; id:Mapped[int]=mapped_column(primary_key=True); entity_type:Mapped[str]=mapped_column(String(30),index=True); entity_id:Mapped[int]=mapped_column(Integer,index=True); path:Mapped[str]=mapped_column(String(500)); original_filename:Mapped[str|None]=mapped_column(String(255)); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
class WebcamLink(Base):
    __tablename__='webcam_links'; id:Mapped[int]=mapped_column(primary_key=True); entity_type:Mapped[str]=mapped_column(String(30),index=True); entity_id:Mapped[int]=mapped_column(Integer,index=True); url:Mapped[str]=mapped_column(String(800)); label:Mapped[str|None]=mapped_column(String(160)); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
class SpotWebcam(Base):
    __tablename__='spot_webcams'
    id:Mapped[int]=mapped_column(primary_key=True)
    spot_id:Mapped[int]=mapped_column(ForeignKey('surf_spots.id'),index=True)
    title:Mapped[str]=mapped_column(String(180))
    operator_name:Mapped[str]=mapped_column(String(180))
    url:Mapped[str]=mapped_column(String(1000))
    description:Mapped[str|None]=mapped_column(Text,nullable=True)
    is_active:Mapped[bool]=mapped_column(Boolean,default=True,index=True)
    sort_order:Mapped[int]=mapped_column(Integer,default=0,index=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    created_by_user_id:Mapped[int|None]=mapped_column(ForeignKey('users.id'),nullable=True)
    approved_source_type:Mapped[str]=mapped_column(String(40),default='operator')
    spot=relationship('SurfSpot'); created_by=relationship('User')
class WebcamSuggestion(Base):
    __tablename__='webcam_suggestions'
    __table_args__=(UniqueConstraint('spot_id','suggested_url','status',name='uq_webcam_suggestion_spot_url_status'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    spot_id:Mapped[int]=mapped_column(ForeignKey('surf_spots.id'),index=True)
    submitted_by_user_id:Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    suggested_url:Mapped[str]=mapped_column(String(1000))
    suggested_title:Mapped[str]=mapped_column(String(180))
    suggested_operator_name:Mapped[str]=mapped_column(String(180))
    submitter_note:Mapped[str|None]=mapped_column(Text,nullable=True)
    status:Mapped[str]=mapped_column(String(30),default='pending',index=True)
    moderator_note:Mapped[str|None]=mapped_column(Text,nullable=True)
    reviewed_by_user_id:Mapped[int|None]=mapped_column(ForeignKey('users.id'),nullable=True)
    submitted_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True)
    reviewed_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    approved_webcam_id:Mapped[int|None]=mapped_column(ForeignKey('spot_webcams.id'),nullable=True)
    spot=relationship('SurfSpot'); submitted_by=relationship('User', foreign_keys=[submitted_by_user_id]); reviewed_by=relationship('User', foreign_keys=[reviewed_by_user_id]); approved_webcam=relationship('SpotWebcam')
class SpotPhoto(Base):
    __tablename__='spot_photos'
    id:Mapped[int]=mapped_column(primary_key=True)
    spot_id:Mapped[int]=mapped_column(ForeignKey('surf_spots.id'),index=True)
    uploaded_by_user_id:Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    display_path:Mapped[str]=mapped_column(String(800))
    thumbnail_path:Mapped[str]=mapped_column(String(800))
    original_filename:Mapped[str|None]=mapped_column(String(255),nullable=True)
    stored_mime_type:Mapped[str]=mapped_column(String(80))
    width:Mapped[int]=mapped_column(Integer)
    height:Mapped[int]=mapped_column(Integer)
    file_size:Mapped[int]=mapped_column(Integer)
    caption:Mapped[str|None]=mapped_column(String(500),nullable=True)
    status:Mapped[str]=mapped_column(String(30),default='active',index=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    spot=relationship('SurfSpot'); uploaded_by=relationship('User')
class CopernicusPublication(Base):
    __tablename__='copernicus_publications'
    __table_args__=(UniqueConstraint('provider','dataset_id','publication_identity',name='uq_copernicus_publication_identity'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    provider:Mapped[str]=mapped_column(String(100),default='copernicus-marine',index=True)
    product_id:Mapped[str]=mapped_column(String(160))
    dataset_id:Mapped[str]=mapped_column(String(220),index=True)
    publication_identity:Mapped[str]=mapped_column(String(500),index=True)
    model_cycle_time:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    latest_available_forecast_time:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    detected_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    ingestion_started_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    ingestion_completed_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    status:Mapped[str]=mapped_column(String(40),index=True)
    error:Mapped[str|None]=mapped_column(Text,nullable=True)
    download_size:Mapped[int|None]=mapped_column(BigInteger,nullable=True)
    checksum:Mapped[str|None]=mapped_column(String(128),nullable=True)
    raw_file_path:Mapped[str|None]=mapped_column(String(800),nullable=True)
    metadata_json:Mapped[dict|None]=mapped_column(JSON,nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
class CopernicusIngestionJob(Base):
    __tablename__='copernicus_ingestion_jobs'
    id:Mapped[int]=mapped_column(primary_key=True)
    publication_id:Mapped[int]=mapped_column(ForeignKey('copernicus_publications.id'),index=True)
    status:Mapped[str]=mapped_column(String(40),index=True)
    lease_token:Mapped[str|None]=mapped_column(String(128),nullable=True)
    lease_until:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    attempts:Mapped[int]=mapped_column(Integer,default=0)
    last_error:Mapped[str|None]=mapped_column(Text,nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    started_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    completed_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    publication=relationship('CopernicusPublication')
