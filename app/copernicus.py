from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .providers import MarineForecastPoint

DEFAULT_PRODUCT_ID = 'GLOBAL_ANALYSISFORECAST_WAV_001_027'
DEFAULT_DATASET_ID = 'cmems_mod_glo_wav_anfc_0.083deg_PT3H-i'
DEFAULT_CACHE_DIR = Path('data/provider-cache/copernicus')
REQUIRED_VARIABLE_MAP = {
    'wave_height': 'VHM0',
    'wave_direction': 'VMDR',
    'wave_period': 'VTPK',
    'swell_wave_height': 'VHM0_SW1',
    'swell_wave_direction': 'VMDR_SW1',
    'swell_wave_period': 'VTM01_SW1',
    'wind_wave_height': 'VHM0_WW',
    'wind_wave_direction': 'VMDR_WW',
    'wind_wave_period': 'VTM01_WW',
}
CORE_VARIABLES = {'VHM0', 'VMDR', 'VTPK'}
OPTIONAL_DECOMPOSITION_VARIABLES = set(REQUIRED_VARIABLE_MAP.values()) - CORE_VARIABLES
DEFAULT_BOUNDS = (-9.15, -8.65, 36.95, 37.60)

# The exact Copernicus variable names must be filled from
# `copernicusmarine describe` / product metadata. Do not use a Copernicus
# Marine product id as the dataset id; toolbox `subset` expects a concrete
# dataset id exposed under the product.
# Keep defaults empty so the app never fabricates a variable mapping.
NORMALIZED_FIELDS = (
    'wave_height',
    'wave_direction',
    'wave_period',
    'swell_wave_height',
    'swell_wave_direction',
    'swell_wave_period',
    'wind_wave_height',
    'wind_wave_direction',
    'wind_wave_period',
)


def copernicusmarine_executable() -> str | None:
    """Find the Copernicus Marine CLI in PATH or the project venv."""
    found = shutil.which('copernicusmarine')
    if found:
        return found
    local = Path.cwd() / '.venv' / 'bin' / 'copernicusmarine'
    if local.exists() and os.access(local, os.X_OK):
        return str(local)
    return None


@dataclass(frozen=True)
class CopernicusConfig:
    enabled: bool
    username: str | None
    password: str | None
    product_id: str = DEFAULT_PRODUCT_ID
    dataset_id: str = DEFAULT_DATASET_ID
    variable_map: dict[str, str] | None = None
    cache_dir: Path = DEFAULT_CACHE_DIR
    min_longitude: float = DEFAULT_BOUNDS[0]
    max_longitude: float = DEFAULT_BOUNDS[1]
    min_latitude: float = DEFAULT_BOUNDS[2]
    max_latitude: float = DEFAULT_BOUNDS[3]

    @property
    def missing_reasons(self) -> list[str]:
        reasons: list[str] = []
        if not self.enabled:
            reasons.append('COPERNICUSMARINE_ENABLED is not true')
        if not self.username:
            reasons.append('COPERNICUSMARINE_USERNAME is not set')
        if not self.password:
            reasons.append('COPERNICUSMARINE_PASSWORD is not set')
        if not self.dataset_id:
            reasons.append('COPERNICUSMARINE_DATASET_ID is not set')
        elif self.dataset_id.startswith('GLOBAL_'):
            reasons.append('COPERNICUSMARINE_DATASET_ID appears to be a product ID, not a concrete dataset ID')
        if self.product_id != DEFAULT_PRODUCT_ID:
            reasons.append('COPERNICUSMARINE_PRODUCT_ID is not the expected GLOBAL_ANALYSISFORECAST_WAV_001_027')
        if self.dataset_id != DEFAULT_DATASET_ID:
            reasons.append('COPERNICUSMARINE_DATASET_ID is not the expected cmems_mod_glo_wav_anfc_0.083deg_PT3H-i')
        if not self.variable_map:
            reasons.append('COPERNICUSMARINE_VARIABLE_MAP_JSON is not set')
        elif self.variable_map != REQUIRED_VARIABLE_MAP:
            reasons.append('COPERNICUSMARINE_VARIABLE_MAP_JSON does not match the required WaveWatch mapping')
        if copernicusmarine_executable() is None:
            reasons.append('copernicusmarine CLI is not installed')
        return reasons

    @property
    def is_ready(self) -> bool:
        return not self.missing_reasons


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if raw in (None, '') else float(raw)


def load_copernicus_config() -> CopernicusConfig:
    raw_map = os.getenv('COPERNICUSMARINE_VARIABLE_MAP_JSON', '').strip().strip("'")
    variable_map: dict[str, str] | None = REQUIRED_VARIABLE_MAP.copy()
    if raw_map:
        parsed = json.loads(raw_map)
        if not isinstance(parsed, dict):
            raise ValueError('COPERNICUSMARINE_VARIABLE_MAP_JSON must be a JSON object')
        variable_map = {str(k): str(v) for k, v in parsed.items() if k in NORMALIZED_FIELDS and v}
    return CopernicusConfig(
        enabled=os.getenv('COPERNICUSMARINE_ENABLED', 'false').lower() == 'true',
        username=os.getenv('COPERNICUSMARINE_USERNAME') or None,
        password=os.getenv('COPERNICUSMARINE_PASSWORD') or None,
        product_id=os.getenv('COPERNICUSMARINE_PRODUCT_ID', DEFAULT_PRODUCT_ID),
        dataset_id=os.getenv('COPERNICUSMARINE_DATASET_ID', DEFAULT_DATASET_ID),
        variable_map=variable_map,
        cache_dir=Path(os.getenv('COPERNICUSMARINE_CACHE_DIR', str(DEFAULT_CACHE_DIR))),
        min_longitude=_float_env('COPERNICUS_MIN_LONGITUDE', DEFAULT_BOUNDS[0]),
        max_longitude=_float_env('COPERNICUS_MAX_LONGITUDE', DEFAULT_BOUNDS[1]),
        min_latitude=_float_env('COPERNICUS_MIN_LATITUDE', DEFAULT_BOUNDS[2]),
        max_latitude=_float_env('COPERNICUS_MAX_LATITUDE', DEFAULT_BOUNDS[3]),
    )


def aljezur_bbox(spots, buffer_degrees: float = 0.15) -> tuple[float, float, float, float]:
    lats = [float(s.latitude) for s in spots]
    lons = [float(s.longitude) for s in spots]
    if not lats or not lons:
        raise ValueError('Cannot build Copernicus bbox without surf spots')
    return (
        min(lons) - buffer_degrees,
        max(lons) + buffer_degrees,
        min(lats) - buffer_degrees,
        max(lats) + buffer_degrees,
    )


def build_subset_command(
    config: CopernicusConfig,
    bbox: tuple[float, float, float, float],
    start: datetime,
    end: datetime,
    output_file: Path,
) -> list[str]:
    if not config.variable_map:
        raise ValueError('Copernicus variable map is required before subset download')
    min_lon, max_lon, min_lat, max_lat = bbox
    executable = copernicusmarine_executable()
    if executable is None:
        raise ValueError('copernicusmarine CLI is not installed')
    command = [
        executable,
        'subset',
        '--dataset-id', config.dataset_id,
        '--minimum-longitude', str(min_lon),
        '--maximum-longitude', str(max_lon),
        '--minimum-latitude', str(min_lat),
        '--maximum-latitude', str(max_lat),
        '--start-datetime', start.astimezone(UTC).isoformat().replace('+00:00', 'Z'),
        '--end-datetime', end.astimezone(UTC).isoformat().replace('+00:00', 'Z'),
        '--output-directory', str(output_file.parent),
        '--output-filename', output_file.name,
        '--force-download',
    ]
    for normalized in NORMALIZED_FIELDS:
        variable = config.variable_map.get(normalized)
        if variable:
            command.extend(['--variable', variable])
    return command


async def run_subset_download(
    config: CopernicusConfig,
    bbox: tuple[float, float, float, float],
    start: datetime,
    end: datetime,
    output_file: Path,
) -> Path:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    command = build_subset_command(config, bbox, start, end, output_file)
    env = os.environ.copy()
    if config.username:
        env['COPERNICUSMARINE_USERNAME'] = config.username
    if config.password:
        env['COPERNICUSMARINE_PASSWORD'] = config.password

    def _run() -> None:
        subprocess.run(command, check=True, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    await asyncio.to_thread(_run)
    return output_file


def _dataset_coord_name(dataset: Any, candidates: tuple[str, ...]) -> str:
    coords = getattr(dataset, 'coords', {})
    data_vars = getattr(dataset, 'data_vars', {})
    for candidate in candidates:
        if candidate in coords or candidate in data_vars:
            return candidate
    raise ValueError(f'None of the coordinate names are available: {candidates}')


def _to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if hasattr(value, 'astype'):
        try:
            seconds = value.astype('datetime64[s]').astype(int)
            return datetime.fromtimestamp(int(seconds), UTC)
        except Exception:
            pass
    text = str(value).replace('Z', '+00:00')
    return datetime.fromisoformat(text).astimezone(UTC)


def _select_nearest_valid_ocean_point(
    dataset: Any,
    latitude: float,
    longitude: float,
    lat_name: str,
    lon_name: str,
    time_name: str,
    variable_map: dict[str, str],
) -> Any:
    """Select nearest point, falling back from coastal land/NaN cells to nearest finite grid cell."""
    selected = dataset.sel({lat_name: latitude, lon_name: longitude}, method='nearest')
    check_var = variable_map.get('wave_height') or next(iter(variable_map.values()), None)
    if not check_var or check_var not in selected:
        return selected
    try:
        first_value = selected[check_var].isel({time_name: 0}).item()
        first_numeric = float(first_value)
        if first_numeric == first_numeric and first_numeric not in (float('inf'), float('-inf')):
            return selected
    except Exception:
        return selected

    try:
        lat_values = list(dataset[lat_name].values)
        lon_values = list(dataset[lon_name].values)
        first_grid = dataset[check_var].isel({time_name: 0})
        candidates: list[tuple[float, Any, Any]] = []
        for lat in lat_values:
            for lon in lon_values:
                value = first_grid.sel({lat_name: lat, lon_name: lon}).item()
                numeric = float(value)
                if numeric != numeric or numeric in (float('inf'), float('-inf')):
                    continue
                distance = (float(lat) - latitude) ** 2 + (float(lon) - longitude) ** 2
                candidates.append((distance, lat, lon))
        if candidates:
            _, lat, lon = min(candidates, key=lambda item: item[0])
            return dataset.sel({lat_name: lat, lon_name: lon})
    except Exception:
        return selected
    return selected


def parse_copernicus_netcdf(
    path: Path,
    latitude: float,
    longitude: float,
    variable_map: dict[str, str],
    provider_name: str = 'copernicus-marine',
) -> list[MarineForecastPoint]:
    try:
        import xarray as xr  # type: ignore
    except ImportError as exc:
        raise RuntimeError('xarray is required to parse Copernicus NetCDF output') from exc

    dataset = xr.open_dataset(path)
    try:
        lat_name = _dataset_coord_name(dataset, ('latitude', 'lat'))
        lon_name = _dataset_coord_name(dataset, ('longitude', 'lon'))
        time_name = _dataset_coord_name(dataset, ('time', 'valid_time'))
        selected = _select_nearest_valid_ocean_point(dataset, latitude, longitude, lat_name, lon_name, time_name, variable_map)
        times = selected[time_name].values
        points: list[MarineForecastPoint] = []
        for index, raw_time in enumerate(times):
            values: dict[str, Any] = {}
            for normalized, source_var in variable_map.items():
                if source_var not in selected:
                    continue
                value = selected[source_var].isel({time_name: index}).item()
                if value is None:
                    continue
                if isinstance(value, (int, float)):
                    numeric = float(value)
                    if numeric != numeric or numeric in (float('inf'), float('-inf')):
                        continue
                    values[normalized] = round(numeric, 4)
                else:
                    values[normalized] = value
            if values:
                points.append(MarineForecastPoint(_to_datetime(raw_time), values, provider_name))
        return points
    finally:
        close = getattr(dataset, 'close', None)
        if close:
            close()
