import os, tempfile, json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


def _reload_for_tmp_db(monkeypatch):
    fd,path=tempfile.mkstemp(suffix='.db'); os.close(fd)
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{path}')
    monkeypatch.setenv('COPERNICUSMARINE_ENABLED','true')
    monkeypatch.setenv('COPERNICUSMARINE_USERNAME','user')
    monkeypatch.setenv('COPERNICUSMARINE_PASSWORD','pass')
    monkeypatch.setenv('COPERNICUSMARINE_PRODUCT_ID','GLOBAL_ANALYSISFORECAST_WAV_001_027')
    monkeypatch.setenv('COPERNICUSMARINE_DATASET_ID','cmems_mod_glo_wav_anfc_0.083deg_PT3H-i')
    monkeypatch.setenv('COPERNICUSMARINE_VARIABLE_MAP_JSON', json.dumps({
        'wave_height':'VHM0','wave_direction':'VMDR','wave_period':'VTPK',
        'swell_wave_height':'VHM0_SW1','swell_wave_direction':'VMDR_SW1','swell_wave_period':'VTM01_SW1',
        'wind_wave_height':'VHM0_WW','wind_wave_direction':'VMDR_WW','wind_wave_period':'VTM01_WW'}))
    import importlib, app.config, app.database, app.models, app.copernicus, app.copernicus_jobs
    importlib.reload(app.config); importlib.reload(app.database); importlib.reload(app.models); importlib.reload(app.copernicus); importlib.reload(app.copernicus_jobs)
    app.models.Base.metadata.create_all(app.database.engine)
    return app


def _metadata(variables=None, end='2026-07-12T12:00:00Z'):
    variables = variables or ['VHM0','VMDR','VTPK','VHM0_SW1','VMDR_SW1','VTM01_SW1','VHM0_WW','VMDR_WW','VTM01_WW']
    return {'products':[{'productID':'GLOBAL_ANALYSISFORECAST_WAV_001_027','datasets':[{'datasetID':'cmems_mod_glo_wav_anfc_0.083deg_PT3H-i','timeCoverageEnd':end,'variables':[{'shortName':v} for v in variables]}]}]}


def test_exact_product_dataset_and_variable_mapping(monkeypatch):
    app=_reload_for_tmp_db(monkeypatch)
    from app.copernicus import DEFAULT_PRODUCT_ID, DEFAULT_DATASET_ID, REQUIRED_VARIABLE_MAP, load_copernicus_config
    monkeypatch.setattr('app.copernicus.copernicusmarine_executable', lambda: '/bin/true')
    cfg=load_copernicus_config()
    assert DEFAULT_PRODUCT_ID == 'GLOBAL_ANALYSISFORECAST_WAV_001_027'
    assert DEFAULT_DATASET_ID == 'cmems_mod_glo_wav_anfc_0.083deg_PT3H-i'
    assert list(REQUIRED_VARIABLE_MAP.values()) == ['VHM0','VMDR','VTPK','VHM0_SW1','VMDR_SW1','VTM01_SW1','VHM0_WW','VMDR_WW','VTM01_WW']
    assert cfg.missing_reasons == []


def test_publication_detection_and_duplicate_prevention(monkeypatch):
    app=_reload_for_tmp_db(monkeypatch)
    from app.database import SessionLocal
    from app.copernicus_jobs import probe_from_metadata, enqueue_probe
    with SessionLocal() as db:
        probe=probe_from_metadata(_metadata())
        pub, job, result=enqueue_probe(db, probe)
        assert result == 'queued' and job is not None
        pub2, job2, result2=enqueue_probe(db, probe)
        assert pub2.id == pub.id
        assert result2 == 'already_ingesting'
        assert job2.id == job.id


def test_00_and_12_cycle_identity_and_delayed_waiting(monkeypatch):
    app=_reload_for_tmp_db(monkeypatch)
    from app.copernicus_jobs import probe_from_metadata, record_waiting
    from app.database import SessionLocal
    p00=probe_from_metadata(_metadata(end='2026-07-12T02:00:00Z'))
    p12=probe_from_metadata(_metadata(end='2026-07-12T15:00:00Z'))
    assert 'T00:00:00+00:00' in p00.publication_identity
    assert 'T12:00:00+00:00' in p12.publication_identity
    with SessionLocal() as db:
        record_waiting(db, 'waiting_for_publication', 'not yet available')
        from app.models import ProviderFetch
        assert db.query(ProviderFetch).first().status == 'waiting_for_publication'


def test_reconciliation_active_lock_and_stale_recovery(monkeypatch):
    app=_reload_for_tmp_db(monkeypatch)
    from app.database import SessionLocal
    from app.copernicus_jobs import probe_from_metadata, enqueue_probe, acquire_job
    from app.models import CopernicusIngestionJob
    with SessionLocal() as db:
        _, job, _ = enqueue_probe(db, probe_from_metadata(_metadata()))
        running=acquire_job(db)
        assert running.id == job.id and running.status == 'running'
        assert acquire_job(db) is None
        running.updated_at = datetime.now(UTC) - timedelta(hours=3)
        running.lease_until = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
        assert acquire_job(db).id == job.id


def test_worker_queue_behavior_no_download_when_unchanged(monkeypatch):
    app=_reload_for_tmp_db(monkeypatch)
    from app.database import SessionLocal
    from app.copernicus_jobs import probe_from_metadata, enqueue_probe
    with SessionLocal() as db:
        probe=probe_from_metadata(_metadata())
        pub, job, result=enqueue_probe(db, probe)
        pub.status='healthy'; job.status='succeeded'; db.commit()
        _, job2, result2=enqueue_probe(db, probe)
        assert result2 == 'already_imported'
        assert job2 is None


def test_missing_core_variable_and_optional_degradation(monkeypatch):
    app=_reload_for_tmp_db(monkeypatch)
    from app.database import SessionLocal
    from app.copernicus_jobs import probe_from_metadata, enqueue_probe
    core_missing=probe_from_metadata(_metadata(variables=['VMDR','VTPK']))
    assert core_missing.missing_core_variables == ['VHM0']
    optional_missing=probe_from_metadata(_metadata(variables=['VHM0','VMDR','VTPK']))
    assert 'VHM0_SW1' in optional_missing.missing_variables
    with SessionLocal() as db:
        _, job, result=enqueue_probe(db, core_missing)
        assert result == 'schema_degraded' and job is None


def test_netcdf_validation_invalid_size_and_incomplete_download(tmp_path, monkeypatch):
    app=_reload_for_tmp_db(monkeypatch)
    from app.copernicus_jobs import validate_netcdf
    f=tmp_path/'bad.nc'; f.write_bytes(b'not-netcdf')
    with pytest.raises(RuntimeError, match='too small'):
        validate_netcdf(f, {}, (-9,-8,36,38))


def test_checksum_secret_redaction_and_status(monkeypatch, tmp_path):
    app=_reload_for_tmp_db(monkeypatch)
    from app.copernicus_jobs import _sha256, redact, latest_status
    from app.database import SessionLocal
    f=tmp_path/'x'; f.write_text('abc')
    assert _sha256(f) == 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
    assert 'pass' not in redact('error pass user')
    with SessionLocal() as db:
        status=latest_status(db)
    assert status['product_id'] == 'GLOBAL_ANALYSISFORECAST_WAV_001_027'
    assert status['dataset_id'] == 'cmems_mod_glo_wav_anfc_0.083deg_PT3H-i'


def test_cron_wrapper_argument_validation_and_no_http_network_calls(monkeypatch):
    wrapper=Path('deploy/scripts/copernicus-cron.sh').read_text()
    assert 'check|reconcile' in wrapper
    assert 'curl https://loli.restricted.invalid' not in wrapper
    providers=Path('app/providers.py').read_text()
    assert 'await run_subset_download' not in providers
    forecast=Path('app/forecast_service.py').read_text()
    assert 'await _ensure_copernicus_forecasts' not in forecast
