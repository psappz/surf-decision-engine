import json
import os
import tempfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.models import Base, SurfSpot
from app.forecast_ledger_models import ConsensusForecastPoint, ConsensusRun
from app.forecast_ledger_repository import create_fetch_attempt, create_forecast_run, create_publication, insert_forecast_points
from app.repositories.consensus_repository import ConsensusRunTransitionError, create_consensus_run, insert_consensus_points, list_consensus_points_for_run, mark_consensus_run_status
from app.services.consensus_configuration import ConfidenceInputWeights, LinearDecay, default_consensus_configuration
from app.services.consensus_engine import ConsensusCalculationRequest, ConsensusEngine
from app.services.consensus_input_selector import select_consensus_inputs, timestamp_available
from app.services.consensus_safety import bounded_json
from app.services.consensus_statistics import WeightedValue, direction_consensus, freshness_factor, quality_adjustment, scalar_consensus, validate_value


def _t(hour: float):
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


def _provider_point(db, provider, *, fetched_hour, issued_hour=0, normalized_hour=None, created_hour=None, valid_hour=12, spot_id=None, normalizer='norm-v1', sample='grid-a', lat=37.294, lon=-8.865, **values):
    spot_id = spot_id or _spot_id(db)
    normalized_hour = fetched_hour if normalized_hour is None else normalized_hour
    created_hour = fetched_hour if created_hour is None else created_hour
    identity = f'{provider}-{fetched_hour}-{normalized_hour}-{normalizer}-{sample}-{len(db.identity_map)}'
    publication = create_publication(db, provider_name=provider, product_id='product', dataset_id=provider, publication_identity=identity, model_cycle_at=_t(issued_hour), source_updated_at=_t(fetched_hour), latest_valid_at=_t(valid_hour), detected_at=_t(fetched_hour), status='detected', metadata_json={})
    fetch = create_fetch_attempt(db, publication_id=publication.id, attempt_number=1, provider_name=provider, status='completed', started_at=_t(fetched_hour), completed_at=_t(fetched_hour), raw_response={'test': True})
    run = create_forecast_run(db, provider_name=provider, publication_id=publication.id, fetch_id=fetch.id, issued_at=_t(issued_hour), fetched_at=_t(fetched_hour), normalized_at=_t(normalized_hour), geographic_bounds_json={}, temporal_bounds_json={}, schema_version='provider-forecast-point-v1', normalizer_version=normalizer, normalizer_configuration_hash=f'{normalizer}-hash', status='succeeded')
    point = _point_for_run(db, run, sample=sample, valid_hour=valid_hour, created_hour=created_hour, lat=lat, lon=lon, **values)
    return run, point


def _point_for_run(db, run, *, sample, valid_hour=12, created_hour=6, lat=37.294, lon=-8.865, **values):
    quality = values.pop('quality_flags_json', {})
    point = insert_forecast_points(db, [{**values, 'forecast_run_id': run.id, 'spot_id': _spot_id(db), 'sample_point_id': sample, 'valid_at': _t(valid_hour), 'raw_values_json': {'selected_latitude': lat, 'selected_longitude': lon}, 'quality_flags_json': quality}])[0]
    point.created_at = _t(created_hour)
    db.commit()
    return point


def _request(db, cfg=None, *, cutoff=7, valid_from=12, valid_until=12, force=False, dry=False, version=None, trigger='test', correlation=None):
    cfg = cfg or default_consensus_configuration()
    return ConsensusCalculationRequest(_t(cutoff), _t(valid_from), _t(valid_until), (_spot_id(db),), version or cfg.engine_version, cfg, trigger, correlation, force, dry)


def _point_for_result(db, result):
    points = list_consensus_points_for_run(db, result.consensus_run_id)
    assert len(points) == 1
    return points[0]


def test_scalar_and_direction_statistics_and_outlier_adjustment():
    cfg = default_consensus_configuration()
    agreeing = scalar_consensus('wave_height', [WeightedValue('a', 1.2, 1, {'freshness_factor': 1, 'spatial_relevance_factor': 1}), WeightedValue('b', 1.3, 1, {'freshness_factor': 1, 'spatial_relevance_factor': 1})], cfg)
    assert agreeing.value == pytest.approx(1.25)
    outlier = scalar_consensus('wave_height', [WeightedValue('a', 1.0, 1, {'freshness_factor': 1, 'spatial_relevance_factor': 1}), WeightedValue('b', 1.1, 1, {'freshness_factor': 1, 'spatial_relevance_factor': 1}), WeightedValue('c', 4.0, 1, {'freshness_factor': 1, 'spatial_relevance_factor': 1})], cfg)
    assert outlier.value < 1.6
    assert any(item.get('adjustment_reason') == 'robust_outlier' for item in outlier.contributors)
    exclude_cfg = replace(cfg, outlier_policy=replace(cfg.outlier_policy, mode='exclude'))
    excluded_outlier = scalar_consensus('wave_height', [WeightedValue('a', 1.0, 1, {'freshness_factor': 1, 'spatial_relevance_factor': 1}), WeightedValue('b', 1.1, 1, {'freshness_factor': 1, 'spatial_relevance_factor': 1}), WeightedValue('c', 4.0, 1, {'freshness_factor': 1, 'spatial_relevance_factor': 1})], exclude_cfg)
    assert any(item.get('excluded') and item.get('adjustment_reason') == 'robust_outlier' for item in excluded_outlier.excluded)
    assert all(not item.get('excluded') for item in excluded_outlier.contributors)
    wrapped = direction_consensus('wave_direction', [WeightedValue('a', 350, 1, {'freshness_factor': 1, 'spatial_relevance_factor': 1}), WeightedValue('b', 10, 1, {'freshness_factor': 1, 'spatial_relevance_factor': 1})], cfg)
    assert wrapped.value == pytest.approx(0, abs=0.001) or wrapped.value == pytest.approx(360, abs=0.001)
    cancelled = direction_consensus('wind_direction', [WeightedValue('a', 90, 1, {'freshness_factor': 1, 'spatial_relevance_factor': 1}), WeightedValue('b', 270, 1, {'freshness_factor': 1, 'spatial_relevance_factor': 1})], cfg)
    assert cancelled.value is None and cancelled.warning == 'directional_cancellation'


def test_minimum_providers_uses_distinct_provider_names():
    cfg = default_consensus_configuration()
    minima = dict(cfg.minimum_providers_per_field); minima['wave_height'] = 2; minima['wave_direction'] = 2
    cfg = replace(cfg, minimum_providers_per_field=minima)
    duplicate = [WeightedValue('same', 1, 1, {}), WeightedValue('same', 2, 1, {})]
    assert scalar_consensus('wave_height', duplicate, cfg).warning == 'insufficient_distinct_providers'
    assert direction_consensus('wave_direction', duplicate, cfg).warning == 'insufficient_distinct_providers'
    distinct = [WeightedValue('a', 1, 1, {}), WeightedValue('b', 2, 1, {})]
    assert scalar_consensus('wave_height', distinct, cfg).value is not None


def test_minimum_providers_nulls_field_and_removes_completeness_credit(db_session):
    cfg = default_consensus_configuration()
    minima = dict(cfg.minimum_providers_per_field); minima['wave_height'] = 2
    cfg = replace(cfg, minimum_providers_per_field=minima, expected_fields=('wave_height',))
    _provider_point(db_session, 'copernicus-marine', fetched_hour=6, wave_height=1.2)
    point = _point_for_result(db_session, ConsensusEngine(db_session).calculate(_request(db_session, cfg)))
    details = point.calculation_details_json['fields']['wave_height']
    assert point.wave_height is None and point.completeness_score == 0
    assert details['warning'] == 'insufficient_distinct_providers'
    assert details['excluded'][0]['exclusion_reason'] == 'insufficient_distinct_providers'


def test_quality_flags_apply_direct_value_once_and_support_lists_and_prefixes():
    cfg = default_consensus_configuration()
    factor, reasons = quality_adjustment({'wave_height': 'interpolated'}, 'wave_height', cfg)
    assert factor == pytest.approx(0.75) and reasons == ['interpolated']
    factor, reasons = quality_adjustment({'wave_height': ['interpolated', 'schema_warning']}, 'wave_height', cfg)
    assert factor == pytest.approx(0.75 * 0.80) and reasons == ['interpolated', 'schema_warning']
    factor, reasons = quality_adjustment({'wave_height.source': 'provider_fallback', 'wave_height_mask': 'masked_grid_value', 'wind_speed': 'interpolated'}, 'wave_height', cfg)
    assert factor == pytest.approx(0.70 * 0.50)
    assert reasons == ['provider_fallback', 'masked_grid_value']


def test_cutoff_timestamp_boundaries_and_legacy_null_policy(db_session):
    assert timestamp_available(_t(6), _t(7))
    assert timestamp_available(_t(7), _t(7))
    assert not timestamp_available(_t(8), _t(7))
    assert not timestamp_available(None, _t(7))
    _provider_point(db_session, 'copernicus-marine', fetched_hour=6, normalized_hour=7, created_hour=7, wave_height=1.0)
    _provider_point(db_session, 'open-meteo-marine', fetched_hour=6, normalized_hour=8, created_hour=6, wave_height=2.0)
    _provider_point(db_session, 'open-meteo-weather', fetched_hour=6, normalized_hour=6, created_hour=8, wind_speed=4.0)
    selection = select_consensus_inputs(db_session, cutoff=_t(7), valid_from=_t(12), valid_until=_t(12), spot_ids=(_spot_id(db_session),), configuration=default_consensus_configuration())
    assert selection.provider_names == ('copernicus-marine',)


def test_maximum_ages_are_enforced_and_boundary_is_inclusive(db_session):
    cfg = default_consensus_configuration()
    cfg = replace(cfg, maximum_provider_age_hours=0.5, source_age_decay=LinearDecay(3, 24))
    _provider_point(db_session, 'copernicus-marine', fetched_hour=6, wave_height=1.0)
    point = _point_for_result(db_session, ConsensusEngine(db_session).calculate(_request(db_session, cfg)))
    excluded = point.calculation_details_json['fields']['wave_height']['excluded']
    assert any(item['exclusion_reason'] == 'maximum_provider_age_exceeded' for item in excluded)
    cfg2 = replace(cfg, maximum_provider_age_hours=1.0)
    point2 = _point_for_result(db_session, ConsensusEngine(db_session).calculate(_request(db_session, cfg2, force=True)))
    assert point2.wave_height == pytest.approx(1.0)
    issue_limited = replace(cfg2, maximum_issue_age_hours=6.0)
    point3 = _point_for_result(db_session, ConsensusEngine(db_session).calculate(_request(db_session, issue_limited, force=True)))
    assert point3.wave_height is None
    assert any(item['exclusion_reason'] == 'maximum_issue_age_exceeded' for item in point3.calculation_details_json['fields']['wave_height']['excluded'])


def test_nearest_sample_selected_per_field_with_one_provider_contribution(db_session):
    run, _ = _provider_point(db_session, 'copernicus-marine', fetched_hour=6, sample='far-z', lat=38.0, lon=-8.865, wave_height=3.0, wave_period=None)
    _point_for_run(db_session, run, sample='near-a', lat=37.295, lon=-8.865, wave_height=1.0, wave_period=None)
    _point_for_run(db_session, run, sample='period-b', lat=37.30, lon=-8.865, wave_height=None, wave_period=12.0)
    point = _point_for_result(db_session, ConsensusEngine(db_session).calculate(_request(db_session)))
    assert point.wave_height == pytest.approx(1.0)
    assert point.wave_period == pytest.approx(12.0)
    height = point.calculation_details_json['fields']['wave_height']
    assert height['contributor_count'] == 1
    assert any(item['exclusion_reason'] == 'less_spatially_relevant_sample' for item in height['excluded'])


def test_expected_fields_validation_subset_and_score_bounds(db_session):
    cfg = default_consensus_configuration()
    with pytest.raises(ValueError, match='unique'):
        replace(cfg, expected_fields=('wave_height', 'wave_height')).validate()
    with pytest.raises(ValueError, match='unknown'):
        replace(cfg, expected_fields=('unknown',)).validate()
    with pytest.raises(ValueError, match='must not be empty'):
        replace(cfg, expected_fields=()).validate()
    with pytest.raises(ValueError, match='integer'):
        replace(cfg, outlier_policy=replace(cfg.outlier_policy, minimum_provider_count_for_exclusion=2.5)).validate()
    _provider_point(db_session, 'copernicus-marine', fetched_hour=6, wave_height=1.0, wave_period=12)
    subset = replace(cfg, expected_fields=('wave_height',), confidence_input_weights=ConfidenceInputWeights(0, 0, 1, 0))
    point = _point_for_result(db_session, ConsensusEngine(db_session).calculate(_request(db_session, subset)))
    assert point.completeness_score == 100 and point.confidence_input_score == 100
    assert 0 <= point.agreement_score <= 100 and 0 <= point.freshness_score <= 100


def test_configured_direction_fields_and_engine_version_mismatch(db_session):
    cfg = default_consensus_configuration()
    _provider_point(db_session, 'copernicus-marine', fetched_hour=6, wave_direction=350)
    _provider_point(db_session, 'open-meteo-marine', fetched_hour=6, wave_direction=10)
    circular = _point_for_result(db_session, ConsensusEngine(db_session).calculate(_request(db_session, cfg)))
    assert min(abs(circular.wave_direction), abs(circular.wave_direction - 360)) <= 2
    scalar_directions = tuple(field for field in cfg.direction_fields if field != 'wave_direction')
    equal_weights = {provider: dict(weights) for provider, weights in cfg.provider_weights_by_field.items()}
    equal_weights['copernicus-marine']['wave_direction'] = 1.0
    equal_weights['open-meteo-marine']['wave_direction'] = 1.0
    changed = replace(cfg, direction_fields=scalar_directions, provider_weights_by_field=equal_weights)
    assert validate_value('wave_direction', -10, changed.direction_fields) == (-10.0, None)
    scalar = _point_for_result(db_session, ConsensusEngine(db_session).calculate(_request(db_session, changed, force=True)))
    assert scalar.wave_direction == pytest.approx(180, abs=1)
    with pytest.raises(ValueError, match='engine_version'):
        ConsensusEngine(db_session).calculate(_request(db_session, cfg, version='different'))
    assert db_session.query(ConsensusRun).count() == 2


def test_exclusion_provenance_for_missing_invalid_zero_weight_quality_and_spatial(db_session):
    # Simulate a legacy invalid row despite the current DB check constraint.
    db_session.execute(sa.text('PRAGMA ignore_check_constraints = ON'))
    run, _ = _provider_point(db_session, 'copernicus-marine', fetched_hour=6, sample='invalid', wave_height=-1, wave_period=None)
    db_session.execute(sa.text('PRAGMA ignore_check_constraints = OFF'))
    _point_for_run(db_session, run, sample='quality', wave_height=2, quality_flags_json={'wave_height': 'missing'})
    _point_for_run(db_session, run, sample='spatial', lat=0, lon=0, wave_height=3)
    _provider_point(db_session, 'ipma', fetched_hour=6, wave_height=9)
    point = _point_for_result(db_session, ConsensusEngine(db_session).calculate(_request(db_session)))
    exclusions = point.calculation_details_json['fields']['wave_height']['excluded']
    reasons = {item['exclusion_reason'] for item in exclusions}
    assert {'negative', 'quality_excluded', 'spatial_relevance_zero', 'zero_provider_field_weight'} <= reasons
    assert all(item.get('excluded') for item in exclusions)


def test_idempotency_force_and_append_only_terminal_transitions(db_session):
    _provider_point(db_session, 'copernicus-marine', fetched_hour=6, wave_height=1.0)
    request = _request(db_session)
    first = ConsensusEngine(db_session).calculate(request)
    second = ConsensusEngine(db_session).calculate(request)
    forced = ConsensusEngine(db_session).calculate(_request(db_session, force=True))
    assert second.status == 'reused' and second.consensus_run_id == first.consensus_run_id
    assert forced.consensus_run_id != first.consensus_run_id
    completed = db_session.get(ConsensusRun, first.consensus_run_id)
    original_metadata = json.loads(json.dumps(completed.metadata_json))
    with pytest.raises(ConsensusRunTransitionError):
        mark_consensus_run_status(db_session, completed.id, 'failed', metadata_json={'mutated': True})
    db_session.rollback(); db_session.refresh(completed)
    assert completed.status == 'completed' and completed.metadata_json == original_metadata
    with pytest.raises(ConsensusRunTransitionError):
        create_consensus_run(db_session, calculated_at=_t(7), forecast_cutoff_at=_t(7), consensus_engine_version='v', configuration_hash='h', status='completed')
    with pytest.raises(ConsensusRunTransitionError):
        insert_consensus_points(db_session, [{'consensus_run_id': completed.id, 'spot_id': _spot_id(db_session), 'valid_at': _t(13), 'provider_count': 0}])
    db_session.rollback()
    failed = create_consensus_run(db_session, calculated_at=_t(7), forecast_cutoff_at=_t(7), consensus_engine_version='v', configuration_hash='h', status='running', metadata_json={'original': True})
    mark_consensus_run_status(db_session, failed.id, 'failed', error_message='original', metadata_json={'original': True})
    db_session.commit()
    with pytest.raises(ConsensusRunTransitionError):
        mark_consensus_run_status(db_session, failed.id, 'completed', error_message='changed', metadata_json={'original': False})
    db_session.rollback(); db_session.refresh(failed)
    assert failed.status == 'failed' and failed.error_message == 'original' and failed.metadata_json == {'original': True}


def test_build_failure_persists_one_redacted_failed_run_and_no_points(db_session, monkeypatch):
    _provider_point(db_session, 'copernicus-marine', fetched_hour=6, wave_height=1.0)
    secret = 'super-secret-password'
    monkeypatch.setenv('DATABASE_PASSWORD', secret)
    def fail(*args, **kwargs):
        raise RuntimeError(f'password={secret} bearer abc.def.ghi https://user:{secret}@example.test/path')
    monkeypatch.setattr(ConsensusEngine, '_build_points', fail)
    with pytest.raises(RuntimeError):
        ConsensusEngine(db_session).calculate(_request(db_session))
    runs = db_session.query(ConsensusRun).all()
    assert len(runs) == 1 and runs[0].status == 'failed'
    assert runs[0].metadata_json['failure_stage'] == 'build_points'
    stored = f"{runs[0].error_message} {runs[0].metadata_json}"
    assert secret not in stored and 'abc.def.ghi' not in stored and 'user:' not in stored
    assert db_session.query(ConsensusForecastPoint).count() == 0


def test_partial_insert_failure_rolls_back_points_and_marks_failed(db_session, monkeypatch):
    import app.services.consensus_engine as engine_module
    _provider_point(db_session, 'copernicus-marine', fetched_hour=6, wave_height=1.0)
    original = engine_module.insert_consensus_points
    def partial_then_fail(db, rows):
        original(db, rows[:1])
        raise RuntimeError('insert failed')
    monkeypatch.setattr(engine_module, 'insert_consensus_points', partial_then_fail)
    with pytest.raises(RuntimeError):
        ConsensusEngine(db_session).calculate(_request(db_session))
    run = db_session.query(ConsensusRun).one()
    assert run.status == 'failed' and run.metadata_json['failure_stage'] == 'insert_points'
    assert db_session.query(ConsensusForecastPoint).count() == 0


def test_oversized_quality_provenance_and_request_metadata_are_bounded(db_session):
    flags = {f'wave_height.flag_{index}': 'x' * 2000 for index in range(100)}
    _provider_point(db_session, 'copernicus-marine', fetched_hour=6, wave_height=1.0, quality_flags_json=flags)
    point = _point_for_result(db_session, ConsensusEngine(db_session).calculate(_request(db_session, trigger='manual', correlation='c' * 128)))
    encoded = json.dumps(point.calculation_details_json, sort_keys=True)
    assert len(encoded.encode()) <= 131_072
    assert 'omitted_count' in encoded or 'truncated' in encoded.lower()
    before = db_session.query(ConsensusRun).count()
    with pytest.raises(ValueError, match='trigger_reason'):
        ConsensusEngine(db_session).calculate(_request(db_session, trigger='x' * 81))
    with pytest.raises(ValueError, match='correlation_id'):
        ConsensusEngine(db_session).calculate(_request(db_session, correlation='x' * 129))
    assert db_session.query(ConsensusRun).count() == before


def test_recursive_provenance_bounds_and_redaction():
    secret = 'token-value-12345'
    os.environ['API_TOKEN'] = secret
    try:
        value = {'password': secret, 'nested': {'items': [{'token': secret, 'text': 'x' * 5000}] * 100}, 'bearer': f'Bearer {secret}'}
        bounded = bounded_json(value, max_depth=4, max_items=5, max_string=40, max_bytes=2000)
        encoded = json.dumps(bounded, sort_keys=True)
        assert len(encoded.encode()) <= 2000
        assert secret not in encoded
        assert 'omitted_count' in encoded or 'truncated' in encoded.lower()
    finally:
        os.environ.pop('API_TOKEN', None)


def test_outlier_exclusion_removes_provider_from_scores_and_provider_count(db_session):
    cfg = default_consensus_configuration()
    cfg = replace(cfg, outlier_policy=replace(cfg.outlier_policy, mode='exclude'))
    _provider_point(db_session, 'copernicus-marine', fetched_hour=6, wave_height=1.0)
    _provider_point(db_session, 'open-meteo-marine', fetched_hour=6, wave_height=1.1)
    _provider_point(db_session, 'mock-open-meteo-marine', fetched_hour=6, wave_height=4.0)
    point = _point_for_result(db_session, ConsensusEngine(db_session).calculate(_request(db_session, cfg)))
    field = point.calculation_details_json['fields']['wave_height']
    assert point.provider_count == 2
    assert 'mock-open-meteo-marine' not in point.provider_ids_json
    assert field['contributor_count'] == 2
    assert any(item.get('provider_name') == 'mock-open-meteo-marine' and item.get('excluded') for item in field['excluded'])


def test_configuration_hash_is_stable_labels_excluded_and_semantics_included():
    cfg = default_consensus_configuration()
    assert cfg.configuration_hash() == default_consensus_configuration().configuration_hash()
    assert cfg.configuration_hash() == replace(cfg, labels={'display_name': 'different'}).configuration_hash()
    perturbations = [
        replace(cfg, maximum_provider_age_hours=23),
        replace(cfg, maximum_issue_age_hours=35),
        replace(cfg, source_age_decay=LinearDecay(2, 24)),
        replace(cfg, model_cycle_decay=LinearDecay(5, 36)),
        replace(cfg, forecast_horizon_decay=LinearDecay(23, 96)),
        replace(cfg, direction_vector_minimum_magnitude=0.4),
        replace(cfg, expected_fields=('wave_height',)),
    ]
    assert all(item.configuration_hash() != cfg.configuration_hash() for item in perturbations)
