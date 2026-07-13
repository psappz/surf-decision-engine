import os
import tempfile
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.models import Base, SurfSpot
from app.forecast_ledger_repository import create_fetch_attempt, create_forecast_run, create_publication, insert_forecast_points
from app.services.consensus_configuration import default_consensus_configuration
from app.services.consensus_engine import ConsensusCalculationRequest, ConsensusEngine
from app.services.consensus_statistics import WeightedValue, direction_consensus, scalar_consensus, freshness_factor


def _t(hour):
    return datetime(2026, 7, 13, 0, 0, tzinfo=UTC) + timedelta(hours=hour)


@pytest.fixture()
def db_session():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    engine = sa.create_engine(f'sqlite:///{path}', future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    db = Session()
    db.add(SurfSpot(code='ARR', slug='arrifana', name='Arrifana', beach_name='Arrifana', zone_name='Aljezur', latitude=37.294, longitude=-8.865, description=None, spot_type='beach break', difficulty='intermediate', is_active_for_recommendations=True, preferred_swell_direction_min=None, preferred_swell_direction_max=None, acceptable_swell_direction_min=None, acceptable_swell_direction_max=None, preferred_swell_height_min=None, preferred_swell_height_max=None, maximum_safe_swell_height_for_profile=None, preferred_period_min=None, preferred_period_max=None, preferred_wind_direction_min=None, preferred_wind_direction_max=None, preferred_tide_min=None, preferred_tide_max=None, tide_preference=None, exposure_factor=None, shelter_factor=None, hazards=None, access_notes=None, base_confidence=None, webcam_url=None, seed_source_note=None, updated_at=_t(0)))
    db.commit()
    try:
        yield db
    finally:
        db.close(); engine.dispose(); os.unlink(path)


def _spot_id(db):
    return db.query(SurfSpot).first().id


def _provider_point(db, provider, *, fetched_hour, issued_hour=0, valid_hour=12, spot_id=None, normalizer='norm-v1', sample='grid-a', attempt=1, **values):
    spot_id = spot_id or _spot_id(db)
    pub = create_publication(db, provider_name=provider, product_id='product', dataset_id=provider, publication_identity=f'{provider}-{fetched_hour}-{normalizer}-{sample}', model_cycle_at=_t(issued_hour), source_updated_at=_t(fetched_hour), latest_valid_at=_t(valid_hour), detected_at=_t(fetched_hour), status='detected', metadata_json={})
    fetch = create_fetch_attempt(db, publication_id=pub.id, attempt_number=attempt, provider_name=provider, status='completed', started_at=_t(fetched_hour), completed_at=_t(fetched_hour), raw_response={'test': True})
    run = create_forecast_run(db, provider_name=provider, publication_id=pub.id, fetch_id=fetch.id, issued_at=_t(issued_hour), fetched_at=_t(fetched_hour), normalized_at=_t(fetched_hour), geographic_bounds_json={}, temporal_bounds_json={}, schema_version='provider-forecast-point-v1', normalizer_version=normalizer, normalizer_configuration_hash=f'{normalizer}-hash', status='succeeded')
    quality = values.pop('quality_flags_json', {})
    point = insert_forecast_points(db, [{**values, 'forecast_run_id': run.id, 'spot_id': spot_id, 'sample_point_id': sample, 'valid_at': _t(valid_hour), 'raw_values_json': {'selected_latitude': 37.294, 'selected_longitude': -8.865}, 'quality_flags_json': quality}])[0]
    db.commit()
    return run, point


def test_scalar_aggregation_agreement_outlier_and_quality_penalty():
    cfg = default_consensus_configuration()
    one = scalar_consensus('wave_height', [WeightedValue('copernicus-marine', 1.2, 1.0, {'freshness_factor': 1, 'spatial_relevance_factor': 1})], cfg)
    assert one.value == pytest.approx(1.2)
    agreeing = scalar_consensus('wave_height', [WeightedValue('a', 1.2, 1, {'freshness_factor': 1, 'spatial_relevance_factor': 1}), WeightedValue('b', 1.3, 1, {'freshness_factor': 1, 'spatial_relevance_factor': 1})], cfg)
    assert agreeing.value == pytest.approx(1.25)
    assert agreeing.agreement_score >= 90
    outlier = scalar_consensus('wave_height', [WeightedValue('a', 1.0, 1, {'freshness_factor': 1, 'spatial_relevance_factor': 1}), WeightedValue('b', 1.1, 1, {'freshness_factor': 1, 'spatial_relevance_factor': 1}), WeightedValue('c', 4.0, 1, {'freshness_factor': 1, 'spatial_relevance_factor': 1})], cfg)
    assert outlier.value < 1.6
    assert any(c.get('exclusion_reason') for c in outlier.contributors)


def test_circular_direction_statistics_wrap_and_cancellation():
    cfg = default_consensus_configuration()
    wrapped = direction_consensus('wave_direction', [WeightedValue('a', 350, 1, {'freshness_factor': 1, 'spatial_relevance_factor': 1}), WeightedValue('b', 10, 1, {'freshness_factor': 1, 'spatial_relevance_factor': 1})], cfg)
    assert wrapped.value == pytest.approx(0, abs=0.001) or wrapped.value == pytest.approx(360, abs=0.001)
    cancelled = direction_consensus('wind_direction', [WeightedValue('a', 90, 1, {'freshness_factor': 1, 'spatial_relevance_factor': 1}), WeightedValue('b', 270, 1, {'freshness_factor': 1, 'spatial_relevance_factor': 1})], cfg)
    assert cancelled.value is None
    assert cancelled.warning == 'directional_cancellation'
    weighted = direction_consensus('wind_direction', [WeightedValue('a', -10, 2, {'freshness_factor': 1, 'spatial_relevance_factor': 1}), WeightedValue('b', 30, 1, {'freshness_factor': 1, 'spatial_relevance_factor': 1})], cfg)
    assert weighted.value > 350 or weighted.value < 10


def test_freshness_cutoff_excludes_future_fetch_and_scores_horizon(db_session):
    cfg = default_consensus_configuration()
    recent, details = freshness_factor(_t(7), _t(6), _t(6), _t(12), cfg)
    stale, _ = freshness_factor(_t(30), _t(0), _t(1), _t(96), cfg)
    assert recent > stale
    assert details['forecast_horizon_hours'] == 6
    _provider_point(db_session, 'copernicus-marine', fetched_hour=6, valid_hour=12, wave_height=1.0)
    _provider_point(db_session, 'copernicus-marine', fetched_hour=9, valid_hour=12, normalizer='norm-v2', wave_height=2.0)
    req = ConsensusCalculationRequest(_t(7), _t(12), _t(12), (_spot_id(db_session),), cfg.engine_version, cfg, 'test')
    result = ConsensusEngine(db_session).calculate(req)
    from app.repositories.consensus_repository import list_consensus_points_for_run
    points = list_consensus_points_for_run(db_session, result.consensus_run_id)
    assert points[0].wave_height == pytest.approx(1.0)
    assert all(c['forecast_run_id'] == 1 for c in points[0].calculation_details_json['fields']['wave_height']['contributors'])


def test_completeness_idempotency_append_only_and_configuration_hash(db_session):
    cfg = default_consensus_configuration()
    _provider_point(db_session, 'copernicus-marine', fetched_hour=6, valid_hour=12, wave_height=1.0, wave_direction=350, wave_period=12)
    _provider_point(db_session, 'mock-open-meteo-weather', fetched_hour=6, valid_hour=12, wind_speed=5, wind_direction=10, wind_gust=8)
    req = ConsensusCalculationRequest(_t(7), _t(12), _t(12), (_spot_id(db_session),), cfg.engine_version, cfg, 'test')
    first = ConsensusEngine(db_session).calculate(req)
    second = ConsensusEngine(db_session).calculate(req)
    forced = ConsensusEngine(db_session).calculate(ConsensusCalculationRequest(_t(7), _t(12), _t(12), (_spot_id(db_session),), cfg.engine_version, cfg, 'test', force_recalculation=True))
    assert first.status == 'completed' and second.status == 'reused' and second.points_written == 0
    assert forced.consensus_run_id != first.consensus_run_id
    from app.repositories.consensus_repository import list_consensus_points_for_run
    point = list_consensus_points_for_run(db_session, first.consensus_run_id)[0]
    assert point.provider_count == 2
    assert 0 < point.completeness_score < 100
    assert point.calculation_details_json['spot_intelligence_applied'] is False
    assert point.calculation_details_json['recommendation_logic_applied'] is False


def test_ipma_zero_direct_hourly_weight_and_shadow_policy(db_session):
    cfg = default_consensus_configuration()
    _provider_point(db_session, 'ipma', fetched_hour=6, valid_hour=12, wave_height=9.0)
    req = ConsensusCalculationRequest(_t(7), _t(12), _t(12), (_spot_id(db_session),), cfg.engine_version, cfg, 'test')
    result = ConsensusEngine(db_session).calculate(req)
    assert result.points_written == 0
    assert cfg.provider_weights_by_field['ipma']['wave_height'] == 0.0
    assert cfg.ipma_corroboration_policy['corroboration_only'] is True


def test_latest_sample_per_provider_prevents_sample_weight_multiplication(db_session):
    cfg = default_consensus_configuration()
    _provider_point(db_session, 'copernicus-marine', fetched_hour=6, valid_hour=12, sample='a', wave_height=1.0)
    _provider_point(db_session, 'copernicus-marine', fetched_hour=6, valid_hour=12, sample='b', normalizer='norm-v2', wave_height=3.0)
    req = ConsensusCalculationRequest(_t(7), _t(12), _t(12), (_spot_id(db_session),), cfg.engine_version, cfg, 'test')
    result = ConsensusEngine(db_session).calculate(req)
    from app.repositories.consensus_repository import list_consensus_points_for_run
    point = list_consensus_points_for_run(db_session, result.consensus_run_id)[0]
    contributors = point.calculation_details_json['fields']['wave_height']['contributors']
    assert len(contributors) == 1
    assert point.wave_height == pytest.approx(3.0)


def test_configuration_hash_is_stable_and_label_independent():
    a = default_consensus_configuration()
    b = default_consensus_configuration()
    b.labels['display_name'] = 'Changed label'
    assert a.configuration_hash() == b.configuration_hash()
    changed = default_consensus_configuration(engine_version='consensus-v2')
    assert a.configuration_hash() != changed.configuration_hash()
