import json
import os
import tempfile
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.models import Base, SurfSpot
from app.repositories.consensus_repository import create_consensus_run, insert_consensus_points, mark_consensus_run_status
from app.repositories.spot_assessment_repository import create_spot_assessment_points, create_spot_assessment_run, mark_spot_assessment_run_status
from app.tools import spot_intelligence as cli

NOW = datetime(2026, 7, 13, 7, tzinfo=UTC)


@pytest.fixture()
def cli_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix='.db'); os.close(fd)
    engine = sa.create_engine(f'sqlite:///{path}', future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    db = Session()
    spot = SurfSpot(code='ARR', slug='arrifana', name='Arrifana', beach_name='Arrifana', zone_name='Aljezur', latitude=37.294, longitude=-8.865, description=None, spot_type='beach break', difficulty='intermediate', is_active_for_recommendations=True, preferred_swell_direction_min=285, preferred_swell_direction_max=350, acceptable_swell_direction_min=250, acceptable_swell_direction_max=30, preferred_swell_height_min=.9, preferred_swell_height_max=2.4, maximum_safe_swell_height_for_profile=3.5, preferred_period_min=10, preferred_period_max=17, preferred_wind_direction_min=70, preferred_wind_direction_max=150, preferred_tide_min=.25, preferred_tide_max=.85, tide_preference='mid', exposure_factor=1, shelter_factor=1, hazards='rocks', access_notes=None, base_confidence=.7, webcam_url=None, seed_source_note=None, updated_at=NOW)
    db.add(spot); db.commit(); monkeypatch.setattr(cli, 'SessionLocal', Session)
    try:
        yield db, spot
    finally:
        db.close(); engine.dispose(); os.unlink(path)


def _consensus(db, spot, points=1):
    run = create_consensus_run(db, calculated_at=NOW, forecast_cutoff_at=NOW, consensus_engine_version='v', configuration_hash='h', status='running')
    insert_consensus_points(db, [{'consensus_run_id': run.id, 'spot_id': spot.id, 'valid_at': NOW + timedelta(hours=i), 'wave_height': 1.2, 'wave_direction': 300, 'wave_period': 12, 'wind_speed': 5, 'wind_direction': 90, 'tide_height': .5, 'provider_count': 1, 'agreement_score': 80, 'freshness_score': 80, 'completeness_score': 80, 'confidence_input_score': 80, 'calculation_details_json': {'spatial_relevance_score': 80}} for i in range(points)])
    mark_consensus_run_status(db, run.id, 'completed'); db.commit(); return run


def _json(capsys):
    return json.loads(capsys.readouterr().out)


def test_cli_calculate_dry_reuse_force_explain_and_id_validation(cli_db, capsys):
    db, spot = cli_db; consensus = _consensus(db, spot)
    args = ['calculate', '--consensus-run-id', str(consensus.id), '--spot-id', str(spot.id)]
    assert cli.main([*args, '--dry-run']) == 0 and _json(capsys)['status'] == 'dry_run'
    assert cli.main(args) == 0; first = _json(capsys); assert first['status'] == 'completed'
    assert cli.main(args) == 0 and _json(capsys)['status'] == 'reused'
    assert cli.main([*args, '--force']) == 0; forced = _json(capsys); assert forced['assessment_run_id'] != first['assessment_run_id']
    from app.forecast_ledger_models import SpotAssessmentPoint
    point = db.query(SpotAssessmentPoint).first()
    assert cli.main(['explain-point', str(point.id)]) == 0
    explanation = _json(capsys); assert explanation['point']['id'] == point.id and explanation['run']['status'] == 'completed'
    assert cli.main(['explain-point', '999']) == 2 and _json(capsys)['error'] == 'spot_assessment_point_not_found'
    with pytest.raises(SystemExit) as exc:
        cli.main(['calculate', '--consensus-run-id', '0'])
    assert exc.value.code == 2


def test_cli_failed_zero_points_distinguished_from_missing_and_redacted(cli_db, capsys, monkeypatch):
    db, spot = cli_db; consensus = _consensus(db, spot)
    secret = 'spot-cli-secret'; monkeypatch.setenv('API_TOKEN', secret)
    run = create_spot_assessment_run(db, consensus_run_id=consensus.id, calculated_at=NOW, spot_rules_version='v', spot_rules_hash='rh', spot_intelligence_engine_version='e', configuration_hash='ch', status='running', metadata_json={'api_key': secret, 'heavy': ['x' * 1000] * 50})
    mark_spot_assessment_run_status(db, run.id, 'failed', error_message=f'Bearer {secret}', metadata_json=run.metadata_json); db.commit()
    assert cli.main(['status']) == 0
    output = capsys.readouterr().out; assert secret not in output and json.loads(output)[0]['point_count'] == 0
    assert cli.main(['inspect-run', str(run.id)]) == 0
    payload = _json(capsys); assert payload['run']['status'] == 'failed' and payload['point_count'] == 0
    assert cli.main(['inspect-run', '999']) == 2 and _json(capsys)['error'] == 'spot_assessment_run_not_found'


@pytest.mark.parametrize('limit', [25, 50, 100])
def test_cli_status_metadata_heavy_pagination(limit, cli_db, capsys, monkeypatch):
    db, spot = cli_db; consensus = _consensus(db, spot)
    secret = 'pagination-secret'; monkeypatch.setenv('API_TOKEN', secret)
    metadata = {'token': secret, 'heavy': [f'{i:02d}-' + 'x' * 600 for i in range(24)]}
    for i in range(100):
        run = create_spot_assessment_run(db, consensus_run_id=consensus.id, calculated_at=NOW + timedelta(seconds=i), spot_rules_version='v', spot_rules_hash=f'rh{i}', spot_intelligence_engine_version='e', configuration_hash='ch', status='running', metadata_json=metadata)
        mark_spot_assessment_run_status(db, run.id, 'failed')
    db.commit()
    assert cli.main(['status', '--limit', str(limit)]) == 0
    output = capsys.readouterr().out; payload = json.loads(output)
    assert len(payload) == limit and len(output.encode()) <= cli.CLI_JSON_MAX_BYTES + 1 and secret not in output


@pytest.mark.parametrize('limit', [25, 50, 100])
def test_cli_inspect_counts_and_truncation(limit, cli_db, capsys):
    db, spot = cli_db; consensus = _consensus(db, spot)
    run = create_spot_assessment_run(db, consensus_run_id=consensus.id, calculated_at=NOW, spot_rules_version='v', spot_rules_hash='rh', spot_intelligence_engine_version='e', configuration_hash='ch', status='running')
    create_spot_assessment_points(db, [{'assessment_run_id': run.id, 'spot_id': spot.id, 'valid_at': NOW + timedelta(hours=i)} for i in range(100)])
    mark_spot_assessment_run_status(db, run.id, 'completed'); db.commit()
    assert cli.main(['inspect-run', str(run.id), '--limit', str(limit)]) == 0
    payload = _json(capsys)
    assert payload['point_count'] == 100 and payload['returned_point_count'] == limit == len(payload['points'])
    assert payload['truncated'] is (limit < 100)
