import os
import tempfile
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker


def _now(offset=0):
    return datetime(2026, 7, 13, 9, 0, tzinfo=UTC) + timedelta(hours=offset)


@pytest.fixture()
def db_session():
    from app.models import Base, SurfSpot

    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    engine = sa.create_engine(f'sqlite:///{path}', future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    db = Session()
    db.add(SurfSpot(code='TST', slug='test-spot', name='Test Spot', beach_name='Test Beach', zone_name='Test Zone', latitude=37.0, longitude=-8.9, description=None, spot_type='beach break', difficulty='intermediate', is_active_for_recommendations=True, preferred_swell_direction_min=None, preferred_swell_direction_max=None, acceptable_swell_direction_min=None, acceptable_swell_direction_max=None, preferred_swell_height_min=None, preferred_swell_height_max=None, maximum_safe_swell_height_for_profile=None, preferred_period_min=None, preferred_period_max=None, preferred_wind_direction_min=None, preferred_wind_direction_max=None, preferred_tide_min=None, preferred_tide_max=None, tide_preference=None, exposure_factor=None, shelter_factor=None, hazards=None, access_notes=None, base_confidence=None, webcam_url=None, seed_source_note=None, updated_at=_now()))
    db.commit()
    try:
        yield db
    finally:
        db.close(); engine.dispose(); os.unlink(path)


def _spot_id(db):
    from app.models import SurfSpot
    return db.query(SurfSpot).first().id


def _request(db, identity='cycle-a', normalizer='norm-v1', config_hash='cfg-v1'):
    from app.services.provider_ledger_writer import ForecastRunDescriptor, NormalizedProviderForecastPoint, ProviderFetchDescriptor, ProviderPublicationDescriptor
    return (
        ProviderPublicationDescriptor('open-meteo-marine', 'open-meteo', 'marine', identity, _now(), _now(), _now(24), _now(), {'test': True}),
        ProviderFetchDescriptor(_now(), _now(), 'healthy', metadata={'attempt': 'test'}),
        ForecastRunDescriptor(_now(), _now(), _now(), {'spot': 'test'}, {'start': _now().isoformat(), 'end': _now(24).isoformat()}, normalizer_version=normalizer, normalizer_configuration_hash=config_hash),
        [NormalizedProviderForecastPoint(_spot_id(db), None, _now(i), wave_height=1.0+i, wave_direction=300, wave_period=12, raw_values={'i': i}, quality_flags={}) for i in range(3)]
    )


def test_provider_ledger_writer_creates_publication_fetch_run_and_points(db_session):
    from app.forecast_ledger_models import ForecastRun, ProviderForecastPoint, ProviderPublication
    from app.models import ProviderFetch
    from app.services.provider_ledger_writer import write_provider_ledger
    db=db_session
    result=write_provider_ledger(db, *_request(db))
    db.commit()
    assert result.forecast_point_count == 3
    assert db.query(ProviderPublication).count() == 1
    assert db.query(ProviderFetch).filter(ProviderFetch.publication_id == result.publication_id).count() == 1
    assert db.query(ForecastRun).count() == 1
    assert db.query(ProviderForecastPoint).count() == 3


def test_provider_ledger_writer_reuses_publication_and_increments_attempts(db_session):
    from app.models import ProviderFetch
    from app.services.provider_ledger_writer import write_provider_ledger
    db=db_session
    r1=write_provider_ledger(db, *_request(db, identity='same-cycle'))
    r2=write_provider_ledger(db, *_request(db, identity='same-cycle', config_hash='cfg-v2'))
    db.commit()
    attempts=[row.attempt_number for row in db.query(ProviderFetch).filter(ProviderFetch.publication_id == r1.publication_id).order_by(ProviderFetch.attempt_number)]
    assert r2.publication_reused is True
    assert attempts == [1, 2]
    assert r1.forecast_run_id != r2.forecast_run_id


def test_duplicate_points_roll_back_batch(db_session):
    from app.forecast_ledger_models import ProviderForecastPoint
    from app.services.provider_ledger_writer import write_provider_ledger
    db=db_session
    publication, fetch, run, points = _request(db)
    points = [points[0], points[0]]
    with pytest.raises(IntegrityError):
        write_provider_ledger(db, publication, fetch, run, points)
    db.rollback()
    assert db.query(ProviderForecastPoint).count() == 0


def test_identity_builders_are_deterministic_and_distinct():
    from app.services.provider_publication_identity import build_copernicus_publication_identity, build_ipma_publication_identity, build_open_meteo_publication_identity
    c1=build_copernicus_publication_identity('GLOBAL_ANALYSISFORECAST_WAV_001_027','cmems_mod_glo_wav_anfc_0.083deg_PT3H-i',_now(),_now(24),{'a':1})
    c2=build_copernicus_publication_identity('GLOBAL_ANALYSISFORECAST_WAV_001_027','cmems_mod_glo_wav_anfc_0.083deg_PT3H-i',_now(),_now(24),{'a':1})
    marine=build_open_meteo_publication_identity('open-meteo-marine',37,-8.9,_now(),_now(24),content={'wave_height':[1]})
    weather=build_open_meteo_publication_identity('open-meteo-weather',37,-8.9,_now(),_now(24),content={'wind_speed_10m':[8]})
    ipma=build_ipma_publication_identity('hp-daily-sea-forecast-day0','https://api.ipma.pt/open-data/forecast/oceanography/hp-daily-sea-forecast-day0.json','2026-07-13T06:00:00','2026-07-13',1081526,'sea')
    assert c1 == c2
    assert marine != weather
    assert ipma.startswith('ipma:')
