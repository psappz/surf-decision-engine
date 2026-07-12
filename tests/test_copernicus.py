from datetime import UTC, datetime, timedelta
from pathlib import Path
import importlib
import os
import sys
import tempfile
import types

import pytest
from fastapi.testclient import TestClient

from app.copernicus import (
    CopernicusConfig,
    aljezur_bbox,
    build_subset_command,
    load_copernicus_config,
    parse_copernicus_netcdf,
)


@pytest.fixture()
def client(monkeypatch):
    fd,path=tempfile.mkstemp(suffix='.db'); os.close(fd)
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{path}')
    import app.config, app.database, app.models, app.main
    importlib.reload(app.config); importlib.reload(app.database); importlib.reload(app.models)
    import app.security, app.seed, app.forecast_service, app.main
    importlib.reload(app.security); importlib.reload(app.seed); importlib.reload(app.forecast_service); importlib.reload(app.main)
    with TestClient(app.main.app) as c:
        yield c


def test_copernicus_config_is_disabled_without_credentials(monkeypatch):
    for key in [
        'COPERNICUSMARINE_ENABLED',
        'COPERNICUSMARINE_USERNAME',
        'COPERNICUSMARINE_PASSWORD',
        'COPERNICUSMARINE_VARIABLE_MAP_JSON',
    ]:
        monkeypatch.delenv(key, raising=False)
    cfg = load_copernicus_config()
    assert cfg.is_ready is False
    assert 'COPERNICUSMARINE_ENABLED is not true' in cfg.missing_reasons
    assert 'COPERNICUSMARINE_USERNAME is not set' in cfg.missing_reasons


def test_subset_command_uses_one_bbox_and_verified_variable_map(tmp_path):
    cfg = CopernicusConfig(
        enabled=True,
        username='user',
        password='secret',
        dataset_id='verified_dataset_id_from_describe',
        variable_map={'wave_height': 'VHM0', 'wave_period': 'VTPK', 'wave_direction': 'VMDR'},
    )
    cmd = build_subset_command(
        cfg,
        (-9.1, -8.6, 37.0, 37.6),
        datetime(2026, 7, 12, tzinfo=UTC),
        datetime(2026, 7, 13, tzinfo=UTC),
        tmp_path / 'latest.nc',
    )
    assert cmd[0].endswith('copernicusmarine')
    assert cmd[1:3] == ['subset', '--dataset-id']
    assert 'verified_dataset_id_from_describe' in cmd
    assert cmd.count('--variable') == 3
    assert '--minimum-longitude' in cmd and '--maximum-latitude' in cmd
    assert str(tmp_path) in cmd
    assert 'secret' not in cmd and 'user' not in cmd


def test_product_id_is_not_treated_as_ready_dataset_id():
    cfg = CopernicusConfig(
        enabled=True,
        username='user',
        password='secret',
        dataset_id='GLOBAL_ANALYSISFORECAST_WAV_001_027',
        variable_map={'wave_height': 'VHM0'},
    )
    assert cfg.is_ready is False
    assert 'COPERNICUSMARINE_DATASET_ID appears to be a product ID, not a concrete dataset ID' in cfg.missing_reasons


def test_aljezur_bbox_wraps_all_spots(client):
    from app.database import SessionLocal
    from app.models import SurfSpot
    db = SessionLocal()
    try:
        spots = db.query(SurfSpot).all()
        min_lon, max_lon, min_lat, max_lat = aljezur_bbox(spots, buffer_degrees=0.01)
        assert min_lon < min(float(s.longitude) for s in spots)
        assert max_lon > max(float(s.longitude) for s in spots)
        assert min_lat < min(float(s.latitude) for s in spots)
        assert max_lat > max(float(s.latitude) for s in spots)
    finally:
        db.close()


class _FakeCoord:
    def __init__(self, values):
        self.values = values


class _FakeValue:
    def __init__(self, values, index=None):
        self.values = values
        self.index = index

    def isel(self, selector):
        return _FakeValue(self.values, list(selector.values())[0])

    def item(self):
        return self.values[self.index]


class _FakeDataset:
    coords = {'time': True, 'latitude': True, 'longitude': True}
    data_vars = {'VHM0': True, 'VTPK': True, 'VMDR': True}

    def __contains__(self, key):
        return key in self.data_vars or key in self.coords

    def __getitem__(self, key):
        if key == 'time':
            return _FakeCoord([datetime(2026, 7, 12, 0, tzinfo=UTC), datetime(2026, 7, 12, 1, tzinfo=UTC)])
        return _FakeValue({'VHM0': [1.23, 1.45], 'VTPK': [12.0, 13.0], 'VMDR': [315.0, 320.0]}[key])

    def sel(self, selector, method=None):
        assert method == 'nearest'
        assert 'latitude' in selector and 'longitude' in selector
        return self

    def close(self):
        self.closed = True


def test_parse_copernicus_netcdf_normalizes_fixture(monkeypatch, tmp_path):
    fake_xarray = types.SimpleNamespace(open_dataset=lambda path: _FakeDataset())
    monkeypatch.setitem(sys.modules, 'xarray', fake_xarray)
    points = parse_copernicus_netcdf(
        tmp_path / 'fixture.nc',
        37.44,
        -8.80,
        {'wave_height': 'VHM0', 'wave_period': 'VTPK', 'wave_direction': 'VMDR'},
    )
    assert len(points) == 2
    assert points[0].provider == 'copernicus-marine'
    assert points[0].values == {'wave_height': 1.23, 'wave_period': 12.0, 'wave_direction': 315.0}


def test_marine_scoring_values_prefer_copernicus_when_same_timestamp(client):
    from app.database import SessionLocal
    from app.forecast_service import _marine_values_for_spot
    from app.models import MarineForecast, SurfSpot
    db = SessionLocal()
    try:
        spot = db.query(SurfSpot).filter_by(slug='odeceixe').one()
        ts = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=8)
        db.add(MarineForecast(provider_name='mock-open-meteo-marine', spot_id=spot.id, forecast_time=ts, fetched_at=ts, values={'wave_height': 1.0}, provider_status='healthy'))
        db.add(MarineForecast(provider_name='copernicus-marine', spot_id=spot.id, forecast_time=ts, fetched_at=ts, values={'wave_height': 2.0}, provider_status='healthy'))
        db.commit()
        values = _marine_values_for_spot(db, spot.id, ts - timedelta(minutes=1), ts + timedelta(minutes=1))
        assert values[ts]['wave_height'] == 2.0
    finally:
        db.close()
