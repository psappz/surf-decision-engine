from datetime import UTC, datetime, timedelta
import threading
import time

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.forecast_ledger_models import SpotAssessmentPoint, SpotAssessmentRun, SpotScoreRun
from app.models import Base, SurfSpot
from app.repositories.spot_score_repository import (
    SpotScoreRunTransitionError,
    count_spot_score_runs,
    count_spot_score_snapshots_for_run,
    create_spot_score_run,
    create_spot_score_snapshots,
    find_equivalent_completed_score,
    find_latest_equivalent_score,
    get_spot_score_run,
    get_spot_score_snapshot,
    latest_spot_score_runs,
    list_spot_score_snapshots_for_run,
    mark_spot_score_run_status,
    next_spot_score_recalculation_sequence,
)
from app.services.spot_scoring_configuration import (
    SpotScoringConfiguration,
    SurferProfileSnapshot,
    default_spot_scoring_configuration,
    surfer_profile_snapshot,
)

NOW = datetime(2026, 7, 13, 9, tzinfo=UTC)


@pytest.fixture()
def db():
    engine = sa.create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    _seed_assessment(session)
    yield session
    session.close()
    engine.dispose()


def _seed_assessment(session):
    spot = SurfSpot(code='TST', slug='test', name='Test', beach_name=None, zone_name=None,
                    latitude=37, longitude=-9, description=None, spot_type=None,
                    difficulty=None, is_active_for_recommendations=True,
                    preferred_swell_direction_min=None, preferred_swell_direction_max=None,
                    acceptable_swell_direction_min=None, acceptable_swell_direction_max=None,
                    preferred_swell_height_min=None, preferred_swell_height_max=None,
                    maximum_safe_swell_height_for_profile=None, preferred_period_min=None,
                    preferred_period_max=None, preferred_wind_direction_min=None,
                    preferred_wind_direction_max=None, preferred_tide_min=None,
                    preferred_tide_max=None, tide_preference=None, exposure_factor=None,
                    shelter_factor=None, hazards=None, access_notes=None, base_confidence=None,
                    webcam_url=None, seed_source_note=None, updated_at=NOW)
    session.add(spot)
    session.flush()
    assessment = SpotAssessmentRun(
        consensus_run_id=1, calculated_at=NOW, spot_rules_version='rules-v1',
        spot_rules_hash='rules-hash', spot_intelligence_engine_version='spot-v1',
        configuration_hash='spot-config', calculation_scope_hash='scope',
        recalculation_sequence=0, status='completed', created_at=NOW,
    )
    session.add(assessment)
    session.flush()
    session.add_all([
        SpotAssessmentPoint(assessment_run_id=assessment.id, spot_id=spot.id,
                            valid_at=NOW + timedelta(hours=i), created_at=NOW)
        for i in range(3)
    ])
    session.commit()


def _run(db, **overrides):
    assessment = db.query(SpotAssessmentRun).one()
    points = db.query(SpotAssessmentPoint).order_by(SpotAssessmentPoint.id).all()
    values = dict(
        assessment_run_id=assessment.id, calculated_at=NOW,
        scoring_configuration=default_spot_scoring_configuration('score-v1'),
        surfer_profile=surfer_profile_snapshot('beginner', profile_version='profile-v1'),
        assessment_point_ids=[point.id for point in points], recalculation_sequence=0,
    )
    values.update(overrides)
    return create_spot_score_run(db, **values)


def _snapshot(point, run_id, **overrides):
    values = dict(score_run_id=run_id, assessment_point_id=point.id,
                  spot_id=point.spot_id, valid_at=point.valid_at,
                  total_score=50, condition_classification='unclassified')
    values.update(overrides)
    return values


def _equivalent(run):
    return dict(assessment_run_id=run.assessment_run_id, engine_version=run.scoring_engine_version,
                configuration_hash=run.scoring_configuration_hash,
                profile_version=run.surfer_profile_version, profile_hash=run.surfer_profile_hash,
                scope_hash=run.calculation_scope_hash)


def test_repository_enforces_running_batches_and_single_terminal_transition(db):
    run = _run(db)
    points = db.query(SpotAssessmentPoint).order_by(SpotAssessmentPoint.id).all()
    rows = create_spot_score_snapshots(db, [_snapshot(points[0], run.id), _snapshot(points[1], run.id)])
    assert len(rows) == 2
    with pytest.raises(SpotScoreRunTransitionError, match='exactly cover'):
        mark_spot_score_run_status(db, run.id, 'completed')
    create_spot_score_snapshots(db, [_snapshot(points[2], run.id)])
    completed = mark_spot_score_run_status(db, run.id, 'completed')
    assert completed.status == 'completed'
    with pytest.raises(SpotScoreRunTransitionError):
        mark_spot_score_run_status(db, run.id, 'failed')
    with pytest.raises(SpotScoreRunTransitionError):
        create_spot_score_snapshots(db, [_snapshot(points[2], run.id)])


def test_repository_requires_completed_typed_assessment_input(db):
    assessment = db.query(SpotAssessmentRun).one()
    assessment.status = 'running'
    db.flush()
    with pytest.raises(SpotScoreRunTransitionError):
        _run(db)
    assessment.status = 'completed'
    with pytest.raises(SpotScoreRunTransitionError):
        _run(db, assessment_run_id=True)


def test_repository_guards_point_provenance_and_redacts_errors(db):
    run = _run(db)
    point = db.query(SpotAssessmentPoint).first()
    with pytest.raises(SpotScoreRunTransitionError):
        create_spot_score_snapshots(db, [_snapshot(point, run.id, spot_id=point.spot_id + 1)])
    with pytest.raises(SpotScoreRunTransitionError):
        create_spot_score_snapshots(db, [_snapshot(point, run.id), _snapshot(point, run.id)])
    failed = mark_spot_score_run_status(
        db, run.id, 'failed', error_message='password=secret token=abc@example.com')
    assert 'secret' not in failed.error_message and 'abc@example.com' not in failed.error_message


def test_repository_equivalence_sequences_and_bounded_reads(db):
    first = _run(db)
    points = db.query(SpotAssessmentPoint).order_by(SpotAssessmentPoint.id).all()
    snapshot = create_spot_score_snapshots(db, [_snapshot(point, first.id) for point in points])[0]
    mark_spot_score_run_status(db, first.id, 'completed')
    second = _run(db, recalculation_sequence=1, calculated_at=NOW + timedelta(minutes=1))
    assert find_equivalent_completed_score(db, **_equivalent(first)).id == first.id
    assert find_latest_equivalent_score(db, **_equivalent(first)).id == second.id
    assert next_spot_score_recalculation_sequence(db, **_equivalent(first)) == 2
    assert get_spot_score_run(db, first.id).id == first.id
    assert get_spot_score_snapshot(db, snapshot.id).id == snapshot.id
    assert count_spot_score_runs(db) == 2
    assert count_spot_score_snapshots_for_run(db, first.id) == 3
    assert list_spot_score_snapshots_for_run(db, first.id, limit=1) == [snapshot]
    assert latest_spot_score_runs(db, limit=1) == [second]
    for bad in (0, 501, True):
        with pytest.raises(ValueError):
            latest_spot_score_runs(db, limit=bad)
    with pytest.raises(ValueError):
        list_spot_score_snapshots_for_run(db, first.id, offset=-1)


def test_repository_and_database_checks_sequence_component_scores_and_restrictive_point_fk(db):
    with pytest.raises(SpotScoreRunTransitionError):
        _run(db, recalculation_sequence=-1)
    run = _run(db)
    point = db.query(SpotAssessmentPoint).first()
    with pytest.raises(SpotScoreRunTransitionError):
        create_spot_score_snapshots(db, [_snapshot(point, run.id, wind_speed_score=101)])


def test_run_persists_canonical_payloads_derived_hashes_and_exact_scope(db):
    points = db.query(SpotAssessmentPoint).order_by(SpotAssessmentPoint.id).all()
    run = _run(db, assessment_point_ids=[points[2].id, points[0].id])
    assert run.calculation_scope_json == [points[0].id, points[2].id]
    assert run.scoring_configuration_hash == default_spot_scoring_configuration(
        'score-v1'
    ).configuration_hash()
    assert run.surfer_profile_name == 'beginner'
    assert run.surfer_profile_json == surfer_profile_snapshot(
        'beginner', profile_version='profile-v1'
    ).canonical_payload()
    assert run.surfer_profile_hash == surfer_profile_snapshot(
        'beginner', profile_version='profile-v1'
    ).profile_hash
    with pytest.raises(SpotScoreRunTransitionError, match='outside'):
        create_spot_score_snapshots(db, [_snapshot(points[1], run.id)])
    create_spot_score_snapshots(
        db, [_snapshot(points[0], run.id), _snapshot(points[2], run.id)]
    )
    assert mark_spot_score_run_status(db, run.id, 'completed').status == 'completed'


def test_repository_rejects_empty_scope_naive_calculation_time_and_unsafe_inputs(db):
    with pytest.raises(SpotScoreRunTransitionError, match='must not be empty'):
        _run(db, assessment_point_ids=[])
    with pytest.raises(SpotScoreRunTransitionError, match='timezone-aware'):
        _run(db, calculated_at=NOW.replace(tzinfo=None))
    run = _run(db)
    point = db.query(SpotAssessmentPoint).first()
    with pytest.raises(SpotScoreRunTransitionError, match='unsupported snapshot fields'):
        create_spot_score_snapshots(db, [_snapshot(point, run.id, surprise='x')])
    with pytest.raises(SpotScoreRunTransitionError, match='safe text'):
        create_spot_score_snapshots(
            db, [_snapshot(point, run.id, condition_classification='bad\nvalue')]
        )


def test_two_session_snapshot_insert_and_completion_are_serialized(tmp_path):
    engine = sa.create_engine(
        f"sqlite:///{tmp_path / 'concurrency.db'}",
        connect_args={'timeout': 5, 'check_same_thread': False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    setup = Session()
    _seed_assessment(setup)
    run = _run(setup)
    run_id = run.id
    setup.commit()
    setup.close()

    writer = Session()
    points = writer.query(SpotAssessmentPoint).order_by(SpotAssessmentPoint.id).all()
    create_spot_score_snapshots(writer, [_snapshot(point, run_id) for point in points])

    started = threading.Event()
    outcome = []

    def complete_in_other_session():
        terminal = Session()
        started.set()
        try:
            outcome.append(mark_spot_score_run_status(terminal, run_id, 'completed').status)
            terminal.commit()
        finally:
            terminal.close()

    thread = threading.Thread(target=complete_in_other_session)
    thread.start()
    assert started.wait(2)
    time.sleep(0.1)
    assert thread.is_alive(), 'terminal session should wait for the snapshot transaction'
    writer.commit()
    thread.join(5)
    assert not thread.is_alive()
    assert outcome == ['completed']
    verify = Session()
    assert verify.get(SpotScoreRun, run_id).status == 'completed'
    assert count_spot_score_snapshots_for_run(verify, run_id) == 3
    verify.close()
    writer.close()
    engine.dispose()


def test_scoring_configuration_is_canonical_validated_and_behavior_only():
    config = default_spot_scoring_configuration()
    same_behavior = SpotScoringConfiguration(engine_version='renamed-v2')
    assert config.configuration_hash() == same_behavior.configuration_hash()
    assert config.canonicalized().effective_values() == config.canonical_payload()
    for bad in (True, float('nan'), float('inf')):
        with pytest.raises(ValueError):
            SpotScoringConfiguration(score_maximum=bad).validate()
    with pytest.raises(ValueError):
        SpotScoringConfiguration(score_minimum=10, score_maximum=10).validate()
    with pytest.raises(ValueError):
        SpotScoringConfiguration(engine_version='bad version').validate()
    with pytest.raises(ValueError):
        default_spot_scoring_configuration('')
    assert SpotScoringConfiguration(score_minimum=-0.0).canonical_payload()['score_minimum'] == 0.0
    assert SpotScoringConfiguration(score_minimum=-0.0).configuration_hash() == (
        SpotScoringConfiguration(score_minimum=0.0).configuration_hash()
    )
    for field in ('score_maximum', 'component_maximum', 'maximum_penalty'):
        with pytest.raises(ValueError):
            SpotScoringConfiguration(**{field: 101}).validate()


def test_compatibility_facade_exports_mature_score_repository():
    import app.forecast_ledger_repository as facade

    for name in (
        'SpotScoreRunTransitionError', 'get_spot_score_run',
        'find_equivalent_completed_score', 'find_latest_equivalent_score',
        'next_spot_score_recalculation_sequence', 'get_spot_score_snapshot',
        'count_spot_score_snapshots_for_run', 'list_spot_score_snapshots_for_run',
        'count_spot_score_runs', 'latest_spot_score_runs',
    ):
        assert name in facade.__all__
        assert getattr(facade, name) is not None


def test_profile_snapshot_validation_hashes_and_unknown_profiles():
    profile = surfer_profile_snapshot('beginner')
    assert profile.canonicalized().effective_values() == profile.canonical_payload()
    assert 'hazard_tolerance' not in profile.canonical_payload()
    assert 'technical_spot_tolerance' not in profile.canonical_payload()
    renamed = SurferProfileSnapshot(profile_name='beginner', profile_version='other-v2',
                                    **profile.effective_values())
    assert renamed.profile_hash == profile.profile_hash
    with pytest.raises(ValueError):
        surfer_profile_snapshot('mystery')
    with pytest.raises(ValueError):
        SurferProfileSnapshot(
            profile_name='beginner', profile_version='v1',
            preferred_breaking_wave_min=True, preferred_breaking_wave_max=1,
            maximum_safe_breaking_wave=2, preferred_period_min=5,
            preferred_period_max=10,
        ).validate()
    with pytest.raises(ValueError):
        SurferProfileSnapshot(
            profile_name='beginner', profile_version='v1',
            preferred_breaking_wave_min=2, preferred_breaking_wave_max=1,
            maximum_safe_breaking_wave=3, preferred_period_min=5,
            preferred_period_max=10,
        ).validate()
