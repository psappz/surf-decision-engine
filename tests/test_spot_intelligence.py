import json
import os
import tempfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.forecast_ledger_models import ConsensusForecastPoint, ConsensusRun, SpotAssessmentPoint, SpotAssessmentRun
from app.models import Base, SurfSpot
from app.repositories.consensus_repository import create_consensus_run, insert_consensus_points, mark_consensus_run_status
from app.repositories.spot_assessment_repository import (
    SpotAssessmentRunTransitionError, create_spot_assessment_points,
    create_spot_assessment_run, mark_spot_assessment_run_status,
)
from app.services.spot_intelligence_configuration import default_spot_intelligence_configuration
from app.services.spot_intelligence_engine import (
    SpotAssessmentRequest, SpotIntelligenceEngine, circular_direction_fit,
    provisional_breaking_range, range_fit, wind_speed_fit_global,
)
from app.services.spot_intelligence_rules import build_spot_rules_snapshot

NOW = datetime(2026, 7, 13, 7, tzinfo=UTC)


def _spot(**changes):
    values = dict(code='ARR', slug='arrifana', name='Arrifana', beach_name='Arrifana', zone_name='Aljezur', latitude=37.294, longitude=-8.865, description=None, spot_type='beach break', difficulty='intermediate', is_active_for_recommendations=True, preferred_swell_direction_min=285.0, preferred_swell_direction_max=350.0, acceptable_swell_direction_min=250.0, acceptable_swell_direction_max=30.0, preferred_swell_height_min=0.9, preferred_swell_height_max=2.4, maximum_safe_swell_height_for_profile=3.5, preferred_period_min=10.0, preferred_period_max=17.0, preferred_wind_direction_min=70.0, preferred_wind_direction_max=150.0, preferred_tide_min=0.25, preferred_tide_max=0.85, tide_preference='mid', exposure_factor=1.0, shelter_factor=1.0, hazards='Rocks near the southern edge.', access_notes=None, base_confidence=.7, webcam_url=None, seed_source_note=None, updated_at=NOW)
    values.update(changes)
    return SurfSpot(**values)


@pytest.fixture()
def db():
    fd, path = tempfile.mkstemp(suffix='.db'); os.close(fd)
    engine = sa.create_engine(f'sqlite:///{path}', future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = Session(); session.add(_spot()); session.commit()
    try:
        yield session
    finally:
        session.close(); engine.dispose(); os.unlink(path)


def _consensus(db, status='completed', *, points=1):
    spot = db.query(SurfSpot).one()
    run = create_consensus_run(db, calculated_at=NOW, forecast_cutoff_at=NOW, consensus_engine_version='consensus-v1', configuration_hash='consensus-hash', status='running', metadata_json={})
    if points:
        insert_consensus_points(db, [{
            'consensus_run_id': run.id, 'spot_id': spot.id, 'valid_at': NOW + timedelta(hours=index),
            'wave_height': 1.5, 'wave_direction': 300, 'wave_period': 12,
            'swell_wave_height': 1.4, 'swell_wave_direction': 305, 'swell_wave_period': 13,
            'wind_speed': 8, 'wind_direction': 90, 'tide_height': .5,
            'provider_count': 2, 'agreement_score': 80, 'freshness_score': 90,
            'completeness_score': 75, 'confidence_input_score': 82,
            'calculation_details_json': {'spatial_relevance_score': 88},
        } for index in range(points)])
    if status != 'running':
        mark_consensus_run_status(db, run.id, status)
    db.commit()
    return run


def _request(run_id, *, force=False, dry=False, spot_ids=None):
    config = default_spot_intelligence_configuration()
    return SpotAssessmentRequest(run_id, spot_ids, config.engine_version, config, force, dry)


def test_circular_direction_preferred_acceptable_outside_and_wraparound():
    cfg = default_spot_intelligence_configuration()
    assert circular_direction_fit(300, 285, 350, 250, 30, cfg) == 100
    partial = circular_direction_fit(10, 285, 350, 250, 30, cfg)
    assert 0 < partial < 100
    assert circular_direction_fit(180, 285, 350, 250, 30, cfg) == 0
    assert circular_direction_fit(355, 350, 10, 330, 30, cfg) == 100


def test_height_period_wind_tide_boundaries_and_missing_rules():
    cfg = default_spot_intelligence_configuration()
    assert range_fit(.9, .9, 2.4) == 100 and range_fit(2.4, .9, 2.4) == 100
    assert range_fit(10, 10, 17) == 100 and range_fit(None, 10, 17) is None
    assert range_fit(.5, None, None) is None
    assert wind_speed_fit_global(10, cfg) == 100
    assert wind_speed_fit_global(25, cfg) == 0
    assert wind_speed_fit_global(None, cfg) is None
    assert range_fit(.25, .25, .85) == 100
    assert range_fit(-.6, .9, 2.4) == 0
    assert range_fit(3.9, .9, 2.4) == 0
    tapered = range_fit(3.0, .9, 2.4)
    above_safe = wind_speed_fit_global(10.001, cfg)
    below_zero = wind_speed_fit_global(24.999, cfg)
    assert tapered is not None and 0 < tapered < 100
    assert above_safe is not None and above_safe < 100
    assert below_zero is not None and below_zero > 0
    assert wind_speed_fit_global(25.001, cfg) == 0
    assert range_fit(.4, .25, .35) == pytest.approx(50)
    assert range_fit(.45, .25, .35) == 0
    assert range_fit(.5, .5, .5) == 100
    assert range_fit(.50001, .5, .5) == 0


def test_breaking_range_order_fallback_and_provisional_label(db):
    cfg = default_spot_intelligence_configuration()
    low, high, details = provisional_breaking_range(0, None, None, 1, 1, None, cfg)
    assert 0 <= low <= high and details['method'] == 'model-derived provisional'
    assert details['observed'] is False and details['live'] is False
    run = _consensus(db)
    point = db.query(ConsensusForecastPoint).one(); point.swell_wave_height = None; db.commit()
    result = SpotIntelligenceEngine(db).calculate(_request(run.id))
    assessment = db.query(SpotAssessmentPoint).filter_by(assessment_run_id=result.assessment_run_id).one()
    encoded = json.dumps(assessment.factor_details_json).lower()
    assert assessment.breaking_wave_min >= 0 and assessment.breaking_wave_max >= assessment.breaking_wave_min
    assert 'total_wave_fallback' in encoded and 'model-derived provisional' in encoded
    assert '"observed": true' not in encoded and '"live": true' not in encoded


def test_breaking_range_honours_non_decimal_rounding_increment():
    cfg = replace(default_spot_intelligence_configuration(), breaking_rounding_metres=.25)
    low, high, details = provisional_breaking_range(1.03, 100, 8, 1, 1, 100, cfg)
    assert low is not None and high is not None
    assert low * 4 == pytest.approx(round(low * 4))
    assert high * 4 == pytest.approx(round(high * 4))
    assert low <= high and details['rounding_increment_m'] == .25


def test_hazards_uncertainty_and_no_scoring_outputs(db):
    run = _consensus(db)
    point = db.query(ConsensusForecastPoint).one(); point.swell_wave_height = 4.0; point.wind_speed = 30; point.tide_height = None; db.commit()
    result = SpotIntelligenceEngine(db).calculate(_request(run.id))
    row = db.query(SpotAssessmentPoint).filter_by(assessment_run_id=result.assessment_run_id).one()
    codes = {item['code'] for item in row.hazard_flags_json}
    uncertainty = json.dumps(row.uncertainty_factors_json)
    details = json.dumps(row.factor_details_json)
    assert {'STATIC_SPOT_HAZARD', 'SWELL_HEIGHT_ABOVE_SPOT_MAXIMUM', 'WIND_SPEED_ABOVE_GLOBAL_THRESHOLD'} <= codes
    assert 'MISSING_INPUT' in uncertainty and 'PROVISIONAL_BREAKING_TRANSFORM' in uncertainty
    assert 'prohibited_outputs_absent' in details
    assert not any(key in row.factor_details_json for key in ('total_score', 'ranking', 'recommendation', 'final_confidence'))


def test_exact_rules_and_configuration_hashing_semantic_perturbations(db):
    spot = db.query(SurfSpot).one()
    first = build_spot_rules_snapshot([spot], version='v1')
    assert first.rules_hash() == build_spot_rules_snapshot([spot], version='v1').rules_hash()
    spot.exposure_factor = 1.1; db.flush()
    assert first.rules_hash() != build_spot_rules_snapshot([spot], version='v1').rules_hash()
    cfg = default_spot_intelligence_configuration()
    assert cfg.configuration_hash() == default_spot_intelligence_configuration().configuration_hash()
    assert cfg.configuration_hash() == replace(cfg, labels={'display': 'changed'}).configuration_hash()
    for changed in (replace(cfg, global_wind_safe_speed=9), replace(cfg, acceptable_direction_fit=55), replace(cfg, breaking_upper_multiplier=1.3), replace(cfg, low_consensus_score_threshold=50)):
        assert changed.configuration_hash() != cfg.configuration_hash()


def test_invalid_metadata_is_deterministic_uncertain_and_hazardous(db):
    spot = db.query(SurfSpot).one(); spot.preferred_period_min = 20; spot.preferred_period_max = 10; spot.exposure_factor = float('nan'); db.commit()
    run = _consensus(db)
    result = SpotIntelligenceEngine(db).calculate(_request(run.id))
    row = db.query(SpotAssessmentPoint).filter_by(assessment_run_id=result.assessment_run_id).one()
    assert row.period_fit is None and row.exposure_adjustment == 1.0
    assert any(item['code'] == 'INVALID_SPOT_METADATA' for item in row.hazard_flags_json)
    assert 'INVALID_SPOT_METADATA_FALLBACK' in json.dumps(row.uncertainty_factors_json)


def test_invalid_consensus_inputs_are_explicit_and_provenance_survives_bounds(db):
    run = _consensus(db)
    point = db.query(ConsensusForecastPoint).one()
    point.wind_direction = 720
    point.wind_speed = -1
    db.commit()
    result = SpotIntelligenceEngine(db).calculate(_request(run.id))
    row = db.query(SpotAssessmentPoint).filter_by(assessment_run_id=result.assessment_run_id).one()
    encoded = json.dumps(row.uncertainty_factors_json)
    assert encoded.count('INVALID_INPUT') >= 2
    assert row.wind_direction_fit is None and row.wind_speed_fit is None
    details = row.factor_details_json
    assert {'formula_version', 'method_label', 'consensus_provenance', 'spot_rules_reference', 'inputs', 'fits', 'transformations', 'consensus_uncertainty_inputs'} <= details.keys()
    assert details['consensus_provenance']['point_id'] == point.id


@pytest.mark.parametrize('state', ['missing', 'running', 'failed'])
def test_rejects_non_completed_consensus_before_writes(db, state):
    run_id = 999 if state == 'missing' else _consensus(db, state).id
    with pytest.raises(ValueError, match='does not exist|not completed'):
        SpotIntelligenceEngine(db).calculate(_request(run_id))
    assert db.query(SpotAssessmentRun).count() == 0


def test_dry_run_is_fresh_write_free_reuse_and_force(db, monkeypatch):
    run = _consensus(db)
    engine = SpotIntelligenceEngine(db)
    first = engine.calculate(_request(run.id))
    reused = engine.calculate(_request(run.id))
    assert reused.status == 'reused' and reused.assessment_run_id == first.assessment_run_id
    calls = []
    original = SpotIntelligenceEngine._build_points
    def observed(self, *args, **kwargs):
        calls.append(args[0]); return original(self, *args, **kwargs)
    monkeypatch.setattr(SpotIntelligenceEngine, '_build_points', observed)
    before = db.query(SpotAssessmentRun).count()
    preview = engine.calculate(_request(run.id, dry=True))
    assert preview.status == 'dry_run' and preview.assessment_run_id is None and calls == [None]
    assert db.query(SpotAssessmentRun).count() == before
    forced = engine.calculate(_request(run.id, force=True))
    assert forced.assessment_run_id != first.assessment_run_id
    first_row = db.get(SpotAssessmentRun, first.assessment_run_id)
    forced_row = db.get(SpotAssessmentRun, forced.assessment_run_id)
    assert first_row.recalculation_sequence == 0
    assert forced_row.recalculation_sequence == 1
    assert first_row.calculation_scope_hash == forced_row.calculation_scope_hash == first.calculation_scope_hash
    forced_again = engine.calculate(_request(run.id, force=True))
    assert db.get(SpotAssessmentRun, forced_again.assessment_run_id).recalculation_sequence == 2


def test_failure_rolls_back_partial_points_redacts_and_leaves_failed_audit(db, monkeypatch):
    import app.services.spot_intelligence_engine as module
    run = _consensus(db)
    secret = 'spot-engine-secret-value'; monkeypatch.setenv('API_TOKEN', secret)
    original = module.create_spot_assessment_points
    def fail(session, rows):
        original(session, rows[:1])
        raise RuntimeError(f'token={secret} Bearer abc.def.ghi')
    monkeypatch.setattr(module, 'create_spot_assessment_points', fail)
    with pytest.raises(RuntimeError):
        SpotIntelligenceEngine(db).calculate(_request(run.id))
    audit = db.query(SpotAssessmentRun).one()
    assert audit.status == 'failed' and db.query(SpotAssessmentPoint).count() == 0
    assert secret not in (audit.error_message + json.dumps(audit.metadata_json))


def test_repository_terminal_immutability(db):
    consensus = _consensus(db)
    run = create_spot_assessment_run(db, consensus_run_id=consensus.id, calculated_at=NOW, spot_rules_version='v', spot_rules_hash='h', spot_intelligence_engine_version='e', configuration_hash='c', status='running')
    create_spot_assessment_points(db, [{'assessment_run_id': run.id, 'spot_id': db.query(SurfSpot).one().id, 'valid_at': NOW}])
    mark_spot_assessment_run_status(db, run.id, 'completed', metadata_json={'original': True}); db.commit()
    with pytest.raises(SpotAssessmentRunTransitionError):
        mark_spot_assessment_run_status(db, run.id, 'failed', metadata_json={'changed': True})
    db.rollback()
    with pytest.raises(SpotAssessmentRunTransitionError):
        create_spot_assessment_points(db, [{'assessment_run_id': run.id, 'spot_id': db.query(SurfSpot).one().id, 'valid_at': NOW + timedelta(hours=1)}])


def test_repository_redacts_terminal_error_messages(db, monkeypatch):
    consensus = _consensus(db)
    secret = 'repository-secret-value'
    monkeypatch.setenv('API_TOKEN', secret)
    run = create_spot_assessment_run(db, consensus_run_id=consensus.id, calculated_at=NOW, spot_rules_version='v', spot_rules_hash='h', spot_intelligence_engine_version='e', configuration_hash='c')
    mark_spot_assessment_run_status(db, run.id, 'failed', error_message=f'token={secret} Bearer abc.def.ghi')
    db.commit()
    assert secret not in db.get(SpotAssessmentRun, run.id).error_message


def test_hash_and_calculation_share_canonical_values_at_rounding_discontinuity():
    below = replace(default_spot_intelligence_configuration(), breaking_upper_multiplier=1.2499999999996)
    above = replace(default_spot_intelligence_configuration(), breaking_upper_multiplier=1.2500000000004)
    assert below.configuration_hash() == above.configuration_hash()
    assert provisional_breaking_range(1, 100, 8, 1, 1, 100, below)[1] != provisional_breaking_range(1, 100, 8, 1, 1, 100, above)[1]
    canonical_below, canonical_above = below.canonicalized(), above.canonicalized()
    assert canonical_below == canonical_above
    assert provisional_breaking_range(1, 100, 8, 1, 1, 100, canonical_below)[1] == provisional_breaking_range(1, 100, 8, 1, 1, 100, canonical_above)[1]


def test_all_invalid_consensus_domains_are_audited_without_misleading_fits(db):
    run = _consensus(db)
    point = db.query(ConsensusForecastPoint).one()
    point.swell_wave_height = -1
    point.swell_wave_direction = 360
    point.swell_wave_period = -1
    point.wind_direction = -1
    point.wind_speed = -1
    point.tide_height = -1
    point.agreement_score = 101
    point.freshness_score = -1
    point.completeness_score = float('nan')
    point.confidence_input_score = 101
    point.calculation_details_json = {'spatial_relevance_score': -1}
    db.commit()
    result = SpotIntelligenceEngine(db).calculate(_request(run.id))
    row = db.query(SpotAssessmentPoint).filter_by(assessment_run_id=result.assessment_run_id).one()
    assert all(value is None for value in (
        row.swell_direction_fit, row.swell_height_fit, row.period_fit,
        row.wind_direction_fit, row.wind_speed_fit, row.tide_fit,
        row.breaking_wave_min, row.breaking_wave_max,
    ))
    factors = row.uncertainty_factors_json['factors']
    assert len([item for item in factors if item['code'] == 'INVALID_INPUT']) >= 6
    assert len([item for item in factors if item['code'] == 'INVALID_CONSENSUS_QUALITY_INPUT']) == 5


def test_failed_zero_attempt_is_durable_and_normal_retry_uses_next_sequence(db, monkeypatch):
    import app.services.spot_intelligence_engine as module
    run = _consensus(db)
    original = module.create_spot_assessment_points

    def fail_first(session, rows):
        raise RuntimeError('first attempt fails')

    monkeypatch.setattr(module, 'create_spot_assessment_points', fail_first)
    with pytest.raises(RuntimeError, match='first attempt fails'):
        SpotIntelligenceEngine(db).calculate(_request(run.id))
    failed = db.query(SpotAssessmentRun).one()
    assert failed.status == 'failed' and failed.recalculation_sequence == 0
    monkeypatch.setattr(module, 'create_spot_assessment_points', original)
    retry = SpotIntelligenceEngine(db).calculate(_request(run.id))
    rows = db.query(SpotAssessmentRun).order_by(SpotAssessmentRun.recalculation_sequence).all()
    assert [(row.status, row.recalculation_sequence) for row in rows] == [('failed', 0), ('completed', 1)]
    assert retry.assessment_run_id == rows[1].id


def test_unique_insert_races_reuse_winner_or_retry_allocation_without_orphans(db, monkeypatch):
    import app.services.spot_intelligence_engine as module
    run = _consensus(db)
    winner = SpotIntelligenceEngine(db).calculate(_request(run.id))
    real_find = module.find_equivalent_completed_assessment
    find_calls = 0

    def hidden_once(*args, **kwargs):
        nonlocal find_calls
        find_calls += 1
        return None if find_calls == 1 else real_find(*args, **kwargs)

    monkeypatch.setattr(module, 'find_equivalent_completed_assessment', hidden_once)
    raced = SpotIntelligenceEngine(db).calculate(_request(run.id))
    assert raced.status == 'reused' and raced.assessment_run_id == winner.assessment_run_id

    real_create = module.create_spot_assessment_run
    create_calls = 0

    def collide_once(*args, **kwargs):
        nonlocal create_calls
        create_calls += 1
        if create_calls == 1:
            raise sa.exc.IntegrityError('insert', {}, Exception('unique race'))
        return real_create(*args, **kwargs)

    monkeypatch.setattr(module, 'create_spot_assessment_run', collide_once)
    forced = SpotIntelligenceEngine(db).calculate(_request(run.id, force=True))
    assert db.get(SpotAssessmentRun, forced.assessment_run_id).recalculation_sequence == 1
    assert db.query(SpotAssessmentRun).filter_by(status='running').count() == 0


def test_scope_is_exact_selected_points_and_rejects_empty_or_unmatched_spots(db):
    run = _consensus(db, points=2)
    result = SpotIntelligenceEngine(db).calculate(_request(run.id))
    audit = db.get(SpotAssessmentRun, result.assessment_run_id)
    point_ids = [point.id for point in db.query(ConsensusForecastPoint).order_by(ConsensusForecastPoint.valid_at)]
    assert audit.metadata_json['selected_consensus_point_ids'] == point_ids
    with pytest.raises(ValueError, match='explicitly empty'):
        SpotIntelligenceEngine(db).calculate(_request(run.id, spot_ids=()))
    with pytest.raises(ValueError, match='no selected consensus points'):
        SpotIntelligenceEngine(db).calculate(_request(run.id, spot_ids=(db.query(SurfSpot).one().id, 999)))
    assert db.query(SpotAssessmentRun).count() == 1


def test_required_provenance_survives_success_and_failure_and_oversize_rejects(db, monkeypatch):
    import app.services.spot_intelligence_engine as module
    run = _consensus(db)
    success = SpotIntelligenceEngine(db).calculate(_request(run.id))
    completed = db.get(SpotAssessmentRun, success.assessment_run_id)
    assert completed.metadata_json['canonical_spot_rules_snapshot']['spots'][0]['spot_id'] == db.query(SurfSpot).one().id
    assert completed.metadata_json['selected_consensus_point_ids'] == [db.query(ConsensusForecastPoint).one().id]

    original = module.create_spot_assessment_points
    def fail_after_audit(session, rows):
        raise RuntimeError('fail after audit')
    monkeypatch.setattr(module, 'create_spot_assessment_points', fail_after_audit)
    with pytest.raises(RuntimeError):
        SpotIntelligenceEngine(db).calculate(_request(run.id, force=True))
    failed = db.query(SpotAssessmentRun).filter_by(status='failed').one()
    assert failed.metadata_json['canonical_spot_rules_snapshot'] == completed.metadata_json['canonical_spot_rules_snapshot']
    assert failed.metadata_json['selected_consensus_point_ids'] == completed.metadata_json['selected_consensus_point_ids']

    monkeypatch.setattr(module, 'create_spot_assessment_points', original)
    other = _consensus(db)
    before = db.query(SpotAssessmentRun).count()
    monkeypatch.setattr(module, 'REQUIRED_PROVENANCE_MAX_BYTES', 10)
    with pytest.raises(ValueError, match='exact required provenance'):
        SpotIntelligenceEngine(db).calculate(_request(other.id))
    assert db.query(SpotAssessmentRun).count() == before
