import os
import subprocess
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

PROJECT_ROOT = Path(__file__).resolve().parents[1]


LEDGER_TABLES = {
    'provider_publications',
    'forecast_runs',
    'provider_forecast_points',
    'consensus_runs',
    'consensus_forecast_points',
    'spot_assessment_runs',
    'spot_assessment_points',
    'spot_score_runs',
    'spot_score_snapshots',
    'confidence_runs',
    'confidence_snapshots',
    'recommendation_snapshots',
}


@pytest.fixture()
def db_session():
    import sqlalchemy as sa
    from sqlalchemy.orm import sessionmaker
    from app.models import Base, SurfSpot

    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    engine = sa.create_engine(f'sqlite:///{path}', future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    db = Session()
    spot = SurfSpot(
        code='TST', slug='test-spot', name='Test Spot', beach_name='Test Beach', zone_name='Test Zone',
        latitude=37.0, longitude=-8.9, description=None, spot_type='beach break', difficulty='intermediate',
        is_active_for_recommendations=True, preferred_swell_direction_min=None, preferred_swell_direction_max=None,
        acceptable_swell_direction_min=None, acceptable_swell_direction_max=None, preferred_swell_height_min=None,
        preferred_swell_height_max=None, maximum_safe_swell_height_for_profile=None, preferred_period_min=None,
        preferred_period_max=None, preferred_wind_direction_min=None, preferred_wind_direction_max=None,
        preferred_tide_min=None, preferred_tide_max=None, tide_preference=None, exposure_factor=None,
        shelter_factor=None, hazards=None, access_notes=None, base_confidence=None, webcam_url=None,
        seed_source_note=None, updated_at=_now(),
    )
    db.add(spot)
    db.commit()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _now(offset=0):
    return datetime(2026, 7, 13, 9, 0, tzinfo=UTC) + timedelta(hours=offset)


def _spot_id(db):
    from app.models import SurfSpot
    return db.query(SurfSpot).order_by(SurfSpot.id).first().id


def _publication(db, provider='copernicus-marine', dataset='dataset-a', identity='cycle-a'):
    from app.forecast_ledger_repository import create_publication
    return create_publication(
        db,
        provider_name=provider,
        product_id='product-a',
        dataset_id=dataset,
        publication_identity=identity,
        model_cycle_at=_now(),
        source_updated_at=_now(),
        latest_valid_at=_now(24),
        detected_at=_now(),
        status='detected',
        metadata_json={'source': 'test'},
    )


def _fetch(db, pub, attempt=1):
    from app.forecast_ledger_repository import create_fetch_attempt
    return create_fetch_attempt(
        db,
        publication_id=pub.id,
        attempt_number=attempt,
        provider_name=pub.provider_name,
        status='started',
        started_at=_now(),
        raw_response={'test': True},
    )


def _run(db, pub, fetch, normalizer='normalizer-v1', issued=None):
    from app.forecast_ledger_repository import create_forecast_run
    return create_forecast_run(
        db,
        provider_name=pub.provider_name,
        publication_id=pub.id,
        fetch_id=fetch.id,
        issued_at=issued or _now(),
        fetched_at=_now(1),
        normalized_at=_now(2),
        geographic_bounds_json={'bbox': [-9, -8, 36, 38]},
        temporal_bounds_json={'start': _now().isoformat(), 'end': _now(24).isoformat()},
        schema_version='forecast-point-v1',
        normalizer_version=normalizer,
        normalizer_configuration_hash='normalizer-cfg-a',
        status='succeeded',
    )


def test_migration_upgrade_and_downgrade_tables():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    env = {**os.environ, 'DATABASE_URL': f'sqlite:///{path}'}
    up = subprocess.run(['.venv/bin/alembic', 'upgrade', 'head'], cwd=PROJECT_ROOT, env=env, text=True, capture_output=True, timeout=120)
    assert up.returncode == 0, up.stderr + up.stdout
    import sqlalchemy as sa
    engine = sa.create_engine(env['DATABASE_URL'])
    names = set(inspect(engine).get_table_names())
    assert LEDGER_TABLES <= names
    assert 'provider_fetches' in names
    columns = {c['name'] for c in inspect(engine).get_columns('provider_fetches')}
    assert {'publication_id', 'attempt_number', 'payload_checksum', 'raw_file_deleted_at'} <= columns
    forecast_columns = {c['name'] for c in inspect(engine).get_columns('forecast_runs')}
    assessment_columns = {c['name'] for c in inspect(engine).get_columns('spot_assessment_runs')}
    score_columns = {c['name'] for c in inspect(engine).get_columns('spot_score_runs')}
    assert 'normalizer_configuration_hash' in forecast_columns
    assert 'configuration_hash' in assessment_columns
    assert 'surfer_profile_hash' in score_columns
    down = subprocess.run(['.venv/bin/alembic', 'downgrade', '0005_user_favs'], cwd=PROJECT_ROOT, env=env, text=True, capture_output=True, timeout=120)
    assert down.returncode == 0, down.stderr + down.stdout
    names_after = set(inspect(engine).get_table_names())
    assert not (LEDGER_TABLES & names_after)
    assert 'provider_fetches' in names_after


def test_repository_facade_preserves_import_compatibility():
    from app.forecast_ledger_repository import create_forecast_run as facade_create_forecast_run
    from app.repositories.forecast_repository import create_forecast_run as split_create_forecast_run
    assert facade_create_forecast_run is split_create_forecast_run


def test_publication_identity_uniqueness_and_nullable_dataset(db_session):
    from app.forecast_ledger_repository import create_publication, get_publication_by_identity
    db = db_session
    if True:
        pub = _publication(db, provider='provider-a', dataset='', identity='same')
        assert get_publication_by_identity(db, 'provider-a', None, 'same').id == pub.id
        _publication(db, provider='provider-b', dataset='', identity='same')
        db.commit()
        with pytest.raises(IntegrityError):
            _publication(db, provider='provider-a', dataset='', identity='same')


def test_fetch_attempts_and_duplicate_attempt_rejected(db_session):
    from app.forecast_ledger_repository import mark_fetch_status
    db = db_session
    if True:
        pub = _publication(db)
        f1 = _fetch(db, pub, 1)
        f2 = _fetch(db, pub, 2)
        mark_fetch_status(db, f1.id, 'failed', completed_at=_now(1), error_code='timeout', raw_file_deleted_at=_now(2), error_message='safe error')
        db.commit()
        assert f1.raw_file_deleted_at is not None and f2.attempt_number == 2
        with pytest.raises(IntegrityError):
            _fetch(db, pub, 2)


def test_forecast_runs_keep_issued_fetched_and_valid_times_distinct(db_session):
    from app.forecast_ledger_repository import insert_forecast_points, list_points_for_run
    db = db_session
    if True:
        pub = _publication(db); fetch = _fetch(db, pub); run = _run(db, pub, fetch, issued=_now(-6)); spot_id = _spot_id(db)
        insert_forecast_points(db, [{'forecast_run_id': run.id, 'spot_id': spot_id, 'sample_point_id': None, 'valid_at': _now(9), 'wave_height': 1.2}])
        db.commit()
        point = list_points_for_run(db, run.id)[0]
        assert run.issued_at != run.fetched_at
        assert run.fetched_at != point.valid_at
        assert point.sample_point_id == ''


def test_multiple_runs_for_same_spot_and_valid_time_do_not_overwrite(db_session):
    from app.forecast_ledger_repository import insert_forecast_points, list_versions_for_spot_and_valid_time
    db = db_session
    if True:
        pub = _publication(db)
        f1 = _fetch(db, pub, 1); f2 = _fetch(db, pub, 2)
        run_a = _run(db, pub, f1, 'normalizer-a')
        run_b = _run(db, pub, f2, 'normalizer-b')
        spot_id = _spot_id(db); valid = _now(9)
        insert_forecast_points(db, [
            {'forecast_run_id': run_a.id, 'spot_id': spot_id, 'sample_point_id': None, 'valid_at': valid, 'wave_height': 1.2},
            {'forecast_run_id': run_b.id, 'spot_id': spot_id, 'sample_point_id': None, 'valid_at': valid, 'wave_height': 1.6},
        ])
        db.commit()
        versions = list_versions_for_spot_and_valid_time(db, spot_id, valid)
        assert [v.wave_height for v in versions] == [1.2, 1.6]
        with pytest.raises(IntegrityError):
            insert_forecast_points(db, [{'forecast_run_id': run_a.id, 'spot_id': spot_id, 'sample_point_id': None, 'valid_at': valid, 'wave_height': 2.0}])


def test_derived_snapshots_and_recommendations_are_append_only(db_session):
    from app.forecast_ledger_repository import (
        create_confidence_run,
        create_confidence_snapshots,
        create_consensus_points,
        create_consensus_run,
        mark_consensus_run_status,
        create_recommendation_snapshot,
        create_spot_assessment_points,
        create_spot_assessment_run,
        mark_spot_assessment_run_status,
        create_spot_score_run,
        mark_spot_score_run_status,
        create_spot_score_snapshots,
        list_recommendation_versions,
    )
    db = db_session
    if True:
        spot_id = _spot_id(db); valid = _now(9)
        c1 = create_consensus_run(db, calculated_at=_now(), forecast_cutoff_at=_now(), consensus_engine_version='cons-v1', configuration_hash='cfg1', status='running')
        c2 = create_consensus_run(db, calculated_at=_now(1), forecast_cutoff_at=_now(1), consensus_engine_version='cons-v2', configuration_hash='cfg2', status='running')
        create_consensus_points(db, [{'consensus_run_id': c1.id, 'spot_id': spot_id, 'valid_at': valid, 'wave_height': 1.2, 'provider_count': 1}])
        mark_consensus_run_status(db, c1.id, 'completed')
        create_consensus_points(db, [{'consensus_run_id': c2.id, 'spot_id': spot_id, 'valid_at': valid, 'wave_height': 1.6, 'provider_count': 2}])
        mark_consensus_run_status(db, c2.id, 'completed')
        ar = create_spot_assessment_run(db, consensus_run_id=c1.id, calculated_at=_now(), spot_rules_version='rules-v1', spot_rules_hash='hash1', spot_intelligence_engine_version='spot-v1', configuration_hash='spot-engine-cfg', status='running')
        assessment_point = create_spot_assessment_points(db, [{'assessment_run_id': ar.id, 'spot_id': spot_id, 'valid_at': valid, 'breaking_wave_min': 0.8, 'breaking_wave_max': 1.3}])[0]
        mark_spot_assessment_run_status(db, ar.id, 'completed')
        sr = create_spot_score_run(db, assessment_run_id=ar.id, calculated_at=_now(), scoring_engine_version='score-v1', scoring_configuration_hash='score-cfg', surfer_profile_version='profile-v1', surfer_profile_hash='profile-hash', status='running')
        create_spot_score_snapshots(db, [{'score_run_id': sr.id, 'assessment_point_id': assessment_point.id, 'spot_id': spot_id, 'valid_at': valid, 'total_score': 82, 'condition_classification': 'go'}])
        mark_spot_score_run_status(db, sr.id, 'completed')
        cr = create_confidence_run(db, calculated_at=_now(), forecast_cutoff_at=_now(), confidence_engine_version='conf-v1', configuration_hash='conf-cfg', status='succeeded')
        create_confidence_snapshots(db, [{'confidence_run_id': cr.id, 'spot_id': spot_id, 'valid_at': valid, 'confidence_score': 74, 'confidence_label': 'medium', 'reasons_json': ['test']}])
        create_recommendation_snapshot(db, recommendation_date=date(2026, 7, 13), daypart='morning', generated_at=_now(), recommended_spot_id=spot_id, recommended_zone='zone-a', score=82, confidence_score=74, confidence_label='medium', forecast_cutoff_at=_now(), consensus_run_id=c1.id, assessment_run_id=ar.id, score_run_id=sr.id, confidence_run_id=cr.id)
        create_recommendation_snapshot(db, recommendation_date=date(2026, 7, 13), daypart='morning', generated_at=_now(1), recommended_spot_id=spot_id, recommended_zone='zone-a', score=84, confidence_score=76, confidence_label='medium', forecast_cutoff_at=_now(1), consensus_run_id=c2.id, assessment_run_id=ar.id, score_run_id=sr.id, confidence_run_id=cr.id)
        db.commit()
        assert len(list_recommendation_versions(db, date(2026, 7, 13), 'morning')) == 2


def test_batch_insert_rolls_back_on_failure(db_session):
    from app.forecast_ledger_models import ProviderForecastPoint
    from app.forecast_ledger_repository import insert_forecast_points
    db = db_session
    if True:
        pub = _publication(db); fetch = _fetch(db, pub); run = _run(db, pub, fetch); spot_id = _spot_id(db); valid = _now(9)
        with pytest.raises(IntegrityError):
            insert_forecast_points(db, [
                {'forecast_run_id': run.id, 'spot_id': spot_id, 'sample_point_id': None, 'valid_at': valid, 'wave_height': 1.2},
                {'forecast_run_id': run.id, 'spot_id': spot_id, 'sample_point_id': None, 'valid_at': valid, 'wave_height': 1.3},
            ])
        db.rollback()
        assert db.query(ProviderForecastPoint).count() == 0
