import json
import os
import tempfile
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.models import Base, SurfSpot
from app.forecast_ledger_repository import create_fetch_attempt, create_forecast_run, create_publication, insert_forecast_points
from app.repositories.consensus_repository import create_consensus_run, mark_consensus_run_status
from app.tools import consensus as cli


@pytest.fixture()
def cli_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix='.db'); os.close(fd)
    engine = sa.create_engine(f'sqlite:///{path}', future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    db = Session()
    now = datetime(2026, 7, 13, 7, tzinfo=UTC)
    spot = SurfSpot(code='ARR', slug='arrifana', name='Arrifana', beach_name='Arrifana', zone_name='Aljezur', latitude=37.294, longitude=-8.865, description=None, spot_type='beach break', difficulty='intermediate', is_active_for_recommendations=True, preferred_swell_direction_min=None, preferred_swell_direction_max=None, acceptable_swell_direction_min=None, acceptable_swell_direction_max=None, preferred_swell_height_min=None, preferred_swell_height_max=None, maximum_safe_swell_height_for_profile=None, preferred_period_min=None, preferred_period_max=None, preferred_wind_direction_min=None, preferred_wind_direction_max=None, preferred_tide_min=None, preferred_tide_max=None, tide_preference=None, exposure_factor=None, shelter_factor=None, hazards=None, access_notes=None, base_confidence=None, webcam_url=None, seed_source_note=None, updated_at=now)
    db.add(spot); db.commit()
    monkeypatch.setattr(cli, 'SessionLocal', Session)
    try:
        yield db, spot, now
    finally:
        db.close(); engine.dispose(); os.unlink(path)


def _seed_point(db, spot, now):
    valid = datetime(2026, 7, 13, 12, tzinfo=UTC)
    publication = create_publication(db, provider_name='copernicus-marine', product_id='p', dataset_id='d', publication_identity='cli-fixture', model_cycle_at=now, source_updated_at=now, latest_valid_at=valid, detected_at=now, status='detected', metadata_json={})
    fetch = create_fetch_attempt(db, publication_id=publication.id, attempt_number=1, provider_name='copernicus-marine', status='completed', started_at=now, completed_at=now, raw_response={})
    run = create_forecast_run(db, provider_name='copernicus-marine', publication_id=publication.id, fetch_id=fetch.id, issued_at=now, fetched_at=now, normalized_at=now, geographic_bounds_json={}, temporal_bounds_json={}, schema_version='v1', normalizer_version='n1', normalizer_configuration_hash='h', status='succeeded')
    point = insert_forecast_points(db, [{'forecast_run_id': run.id, 'spot_id': spot.id, 'sample_point_id': 'grid', 'valid_at': valid, 'wave_height': 1.2, 'raw_values_json': {'selected_latitude': spot.latitude, 'selected_longitude': spot.longitude}, 'quality_flags_json': {}}])[0]
    point.created_at = now
    db.commit()


def _json(capsys):
    return json.loads(capsys.readouterr().out)


def test_cli_rejects_negative_horizon_inverted_range_and_nonpositive_ids(cli_db):
    with pytest.raises(SystemExit) as error:
        cli.main(['calculate-latest', '--hours', '-1'])
    assert error.value.code == 2
    with pytest.raises(SystemExit) as error:
        cli.main(['calculate', '--cutoff', '2026-07-13T07:00:00Z', '--valid-from', '2026-07-14T00:00:00Z', '--valid-until', '2026-07-13T00:00:00Z'])
    assert error.value.code == 2
    with pytest.raises(SystemExit) as error:
        cli.main(['inspect-run', '0'])
    assert error.value.code == 2


def test_cli_status_and_inspect_distinguish_zero_point_failed_from_missing(cli_db, capsys, monkeypatch):
    db, _, now = cli_db
    secret = 'cli-secret-token'
    monkeypatch.setenv('API_TOKEN', secret)
    run = create_consensus_run(db, calculated_at=now, forecast_cutoff_at=now, consensus_engine_version='v', configuration_hash='h', status='running', metadata_json={'password': secret, 'oversized': [{'token': secret, 'text': 'x' * 5000}] * 100})
    mark_consensus_run_status(db, run.id, 'failed', error_message=f'Bearer {secret} https://user:{secret}@example.test/path', metadata_json=run.metadata_json)
    db.commit()
    assert cli.main(['status']) == 0
    output = capsys.readouterr().out
    assert secret not in output
    payload = json.loads(output)
    assert payload[0]['status'] == 'failed' and payload[0]['point_count'] == 0
    assert cli.main(['inspect-run', str(run.id)]) == 0
    payload = _json(capsys)
    assert payload['point_count'] == 0 and payload['run']['status'] == 'failed'
    assert cli.main(['inspect-run', '999']) == 2
    assert _json(capsys)['error'] == 'consensus_run_not_found'


def test_cli_dry_run_force_and_explain_existing_and_missing(cli_db, capsys):
    db, spot, now = cli_db
    _seed_point(db, spot, now)
    args = ['calculate', '--cutoff', '2026-07-13T07:00:00Z', '--valid-from', '2026-07-13T12:00:00Z', '--valid-until', '2026-07-13T12:00:00Z', '--spot-id', str(spot.id)]
    assert cli.main([*args, '--dry-run']) == 0
    assert _json(capsys)['status'] == 'dry_run'
    assert cli.main(args) == 0
    first = _json(capsys); assert first['status'] == 'completed'
    assert cli.main(args) == 0
    assert _json(capsys)['status'] == 'reused'
    assert cli.main([*args, '--force']) == 0
    forced = _json(capsys); assert forced['status'] == 'completed' and forced['consensus_run_id'] != first['consensus_run_id']
    from app.forecast_ledger_models import ConsensusForecastPoint
    point = db.query(ConsensusForecastPoint).first()
    assert cli.main(['explain-point', str(point.id)]) == 0
    payload = _json(capsys)
    assert payload['point']['id'] == point.id and payload['run']['status'] == 'completed'
    assert cli.main(['explain-point', '999']) == 2
    assert _json(capsys)['error'] == 'consensus_point_not_found'
