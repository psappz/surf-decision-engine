from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from .copernicus import (
    CORE_VARIABLES,
    DEFAULT_DATASET_ID,
    DEFAULT_PRODUCT_ID,
    NORMALIZED_FIELDS,
    REQUIRED_VARIABLE_MAP,
    build_subset_command,
    copernicusmarine_executable,
    load_copernicus_config,
    parse_copernicus_netcdf,
)
from .forecast_service import calculate_recommendations
from .models import CopernicusIngestionJob, CopernicusPublication, MarineForecast, ProviderFetch, SurfSpot
from .services.provider_ledger_writer import ForecastRunDescriptor, NormalizedProviderForecastPoint, ProviderFetchDescriptor, ProviderPublicationDescriptor, ledger_writes_enabled, mark_ledger_failure, write_provider_ledger
from .services.provider_publication_identity import build_copernicus_publication_identity

PROVIDER = 'copernicus-marine'
JOB_LEASE_MINUTES = 120
MIN_PLAUSIBLE_NETCDF_SIZE = 1024
RAW_RETAIN_SUCCESS = 4
FAILED_RETAIN_DAYS = 7


@dataclass(frozen=True)
class PublicationProbe:
    product_id: str
    dataset_id: str
    publication_identity: str
    model_cycle_time: datetime | None
    latest_available_forecast_time: datetime | None
    metadata: dict[str, Any]
    missing_variables: list[str]
    missing_core_variables: list[str]


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime | None) -> datetime | None:
    if not dt:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def redact(text: str | None) -> str | None:
    if text is None:
        return None
    redacted = text
    for key in ('COPERNICUSMARINE_PASSWORD', 'COPERNICUSMARINE_USERNAME'):
        value = os.environ.get(key)
        if value:
            redacted = redacted.replace(value, '[REDACTED]')
    return redacted


def configured_bbox() -> tuple[float, float, float, float]:
    cfg = load_copernicus_config()
    return (cfg.min_longitude, cfg.max_longitude, cfg.min_latitude, cfg.max_latitude)


def temporal_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or _now()
    start = now - timedelta(hours=24)
    end = now + timedelta(days=int(os.getenv('COPERNICUS_FORECAST_DAYS', '5')))
    return start, end


def run_toolbox_describe() -> dict[str, Any]:
    cfg = load_copernicus_config()
    exe = copernicusmarine_executable()
    if not exe:
        raise RuntimeError('copernicusmarine CLI is not installed')
    cmd = [exe, 'describe', '--product-id', cfg.product_id, '--return-fields', 'all', '--disable-progress-bar', '--log-level', 'ERROR', '--raise-on-error']
    env = os.environ.copy()
    result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError('copernicusmarine describe did not return JSON') from exc


def _walk(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk(item)


def _dataset_nodes(metadata: dict[str, Any], dataset_id: str) -> list[dict[str, Any]]:
    nodes = []
    for node in _walk(metadata):
        values = {str(v) for v in node.values() if isinstance(v, str)}
        if dataset_id in values:
            nodes.append(node)
    return nodes


def _variables_in_metadata(metadata: dict[str, Any], dataset_id: str) -> set[str]:
    names: set[str] = set()
    nodes = _dataset_nodes(metadata, dataset_id) or [metadata]
    wanted = set(REQUIRED_VARIABLE_MAP.values())
    for node in nodes:
        for child in _walk(node):
            for key in ('shortName', 'standardName', 'name', 'variable', 'variableShortName'):
                value = child.get(key) if isinstance(child, dict) else None
                if isinstance(value, str) and value in wanted:
                    names.add(value)
            for value in child.values() if isinstance(child, dict) else []:
                if isinstance(value, str) and value in wanted:
                    names.add(value)
    return names


def _parse_times_from_metadata(metadata: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    texts = json.dumps(metadata, default=str)
    matches = sorted(set(re.findall(r'20\d\d-\d\d-\d\dT\d\d:\d\d(?::\d\d)?(?:\.\d+)?Z?', texts)))
    parsed: list[datetime] = []
    for item in matches:
        try:
            parsed.append(datetime.fromisoformat(item.replace('Z', '+00:00')).astimezone(UTC))
        except ValueError:
            continue
    latest = max(parsed) if parsed else None
    cycle = None
    if latest:
        hour = 12 if latest.hour >= 12 else 0
        cycle = latest.replace(hour=hour, minute=0, second=0, microsecond=0)
    return cycle, latest


def probe_from_metadata(metadata: dict[str, Any]) -> PublicationProbe:
    cfg = load_copernicus_config()
    dataset_nodes = _dataset_nodes(metadata, cfg.dataset_id)
    if not dataset_nodes:
        raise RuntimeError(f'Configured dataset {cfg.dataset_id} was not found in Copernicus catalogue metadata')
    available = _variables_in_metadata(metadata, cfg.dataset_id)
    missing = [v for v in REQUIRED_VARIABLE_MAP.values() if v not in available]
    missing_core = [v for v in missing if v in CORE_VARIABLES]
    cycle_time, latest_time = _parse_times_from_metadata({'dataset': dataset_nodes})
    fingerprint_src = json.dumps(dataset_nodes, sort_keys=True, default=str)
    fingerprint = hashlib.sha256(fingerprint_src.encode()).hexdigest()[:16]
    identity = f'{cfg.product_id}:{cfg.dataset_id}:{cycle_time.isoformat() if cycle_time else "unknown-cycle"}:{latest_time.isoformat() if latest_time else fingerprint}'
    return PublicationProbe(cfg.product_id, cfg.dataset_id, identity, cycle_time, latest_time, {'fingerprint': fingerprint}, missing, missing_core)


def detect_publication() -> PublicationProbe:
    return probe_from_metadata(run_toolbox_describe())


def record_waiting(db: Session, status: str = 'waiting_for_publication', error: str | None = None) -> None:
    now = _now()
    cfg = load_copernicus_config()
    pf = ProviderFetch(provider_name=PROVIDER, fetched_at=now, latitude=None, longitude=None, status=status, raw_response={'product_id': cfg.product_id, 'dataset_id': cfg.dataset_id}, parsing_errors=redact(error), data_age_seconds=None)
    db.add(pf)
    db.commit()


def enqueue_probe(db: Session, probe: PublicationProbe) -> tuple[CopernicusPublication, CopernicusIngestionJob | None, str]:
    now = _now()
    existing = db.query(CopernicusPublication).filter_by(provider=PROVIDER, dataset_id=probe.dataset_id, publication_identity=probe.publication_identity).first()
    if existing:
        active = db.query(CopernicusIngestionJob).filter(CopernicusIngestionJob.publication_id == existing.id, CopernicusIngestionJob.status.in_(['queued', 'running'])).first()
        if active:
            return existing, active, 'already_ingesting'
        if existing.status == 'healthy':
            return existing, None, 'already_imported'
        if probe.missing_core_variables:
            existing.status = 'degraded'
            existing.error = f"Missing core variables: {', '.join(probe.missing_core_variables)}"
            existing.updated_at = now
            db.commit()
            return existing, None, 'schema_degraded'
        job = CopernicusIngestionJob(publication_id=existing.id, status='queued', attempts=0, created_at=now, updated_at=now)
        existing.status = 'queued'
        existing.updated_at = now
        db.add(job)
        db.commit()
        return existing, job, 'queued'
    status = 'degraded' if probe.missing_core_variables else 'queued'
    pub = CopernicusPublication(provider=PROVIDER, product_id=probe.product_id, dataset_id=probe.dataset_id, publication_identity=probe.publication_identity, model_cycle_time=probe.model_cycle_time, latest_available_forecast_time=probe.latest_available_forecast_time, detected_at=now, status=status, error=(f"Missing core variables: {', '.join(probe.missing_core_variables)}" if probe.missing_core_variables else (f"Missing optional variables: {', '.join(probe.missing_variables)}" if probe.missing_variables else None)), metadata_json={'missing_variables': probe.missing_variables, **probe.metadata}, created_at=now, updated_at=now)
    db.add(pub)
    db.flush()
    if probe.missing_core_variables:
        db.commit()
        return pub, None, 'schema_degraded'
    job = CopernicusIngestionJob(publication_id=pub.id, status='queued', attempts=0, created_at=now, updated_at=now)
    db.add(job)
    db.commit()
    return pub, job, 'queued'


def enqueue_latest(db: Session) -> tuple[str, int | None]:
    probe = detect_publication()
    pub, job, result = enqueue_probe(db, probe)
    return result, job.id if job else None


def acquire_job(db: Session) -> CopernicusIngestionJob | None:
    now = _now()
    stale_before = now - timedelta(minutes=JOB_LEASE_MINUTES)
    job = db.query(CopernicusIngestionJob).filter(
        (CopernicusIngestionJob.status == 'queued') |
        ((CopernicusIngestionJob.status == 'running') & ((CopernicusIngestionJob.lease_until == None) | (CopernicusIngestionJob.lease_until < now) | (CopernicusIngestionJob.updated_at < stale_before)))
    ).order_by(CopernicusIngestionJob.created_at).first()
    if not job:
        return None
    token = secrets.token_hex(16)
    job.status = 'running'
    job.lease_token = token
    job.lease_until = now + timedelta(minutes=JOB_LEASE_MINUTES)
    job.attempts = (job.attempts or 0) + 1
    job.started_at = job.started_at or now
    job.updated_at = now
    job.publication.status = 'ingesting'
    job.publication.ingestion_started_at = job.publication.ingestion_started_at or now
    job.publication.updated_at = now
    db.commit()
    return job


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def validate_netcdf(path: Path, variable_map: dict[str, str], bbox: tuple[float, float, float, float]) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError('Downloaded NetCDF file does not exist')
    size = path.stat().st_size
    if size < MIN_PLAUSIBLE_NETCDF_SIZE:
        raise RuntimeError(f'Downloaded NetCDF file is too small: {size} bytes')
    try:
        import xarray as xr  # type: ignore
    except ImportError as exc:
        raise RuntimeError('xarray is required for NetCDF validation') from exc
    ds = xr.open_dataset(path)
    try:
        data_vars = set(getattr(ds, 'data_vars', {}).keys())
        missing_core = [v for v in CORE_VARIABLES if v not in data_vars]
        if missing_core:
            raise RuntimeError(f'Missing core variables: {", ".join(sorted(missing_core))}')
        missing_optional = [v for v in REQUIRED_VARIABLE_MAP.values() if v not in data_vars and v not in CORE_VARIABLES]
        lat_name = 'latitude' if 'latitude' in ds.coords else 'lat'
        lon_name = 'longitude' if 'longitude' in ds.coords else 'lon'
        time_name = 'time' if 'time' in ds.coords else 'valid_time'
        for name in (lat_name, lon_name, time_name):
            if name not in ds.coords and name not in ds:
                raise RuntimeError(f'Missing coordinate {name}')
        if len(ds[time_name]) == 0:
            raise RuntimeError('NetCDF time dimension is empty')
        min_lon, max_lon, min_lat, max_lat = bbox
        lats = [float(x) for x in ds[lat_name].values]
        lons = [float(x) for x in ds[lon_name].values]
        if max(lats) < min_lat or min(lats) > max_lat or max(lons) < min_lon or min(lons) > max_lon:
            raise RuntimeError('NetCDF coordinates do not cover configured region')
        times = [str(x) for x in ds[time_name].values]
        if times != sorted(times):
            raise RuntimeError('NetCDF timestamps are not monotonic')
        return {'size': size, 'missing_optional_variables': missing_optional, 'time_count': len(times), 'lat_count': len(lats), 'lon_count': len(lons)}
    finally:
        close = getattr(ds, 'close', None)
        if close:
            close()


def _ledger_point_from_copernicus(spot_id: int, point) -> NormalizedProviderForecastPoint:
    values = point.values or {}
    quality_flags = {key: 'missing' for key in ('wave_height', 'wave_direction', 'wave_period') if values.get(key) is None}
    return NormalizedProviderForecastPoint(
        spot_id=spot_id,
        sample_point_id=values.get('sample_point_id') or values.get('selected_grid'),
        valid_at=point.timestamp,
        wave_height=values.get('wave_height'),
        wave_direction=values.get('wave_direction'),
        wave_period=values.get('wave_period'),
        swell_wave_height=values.get('swell_wave_height'),
        swell_wave_direction=values.get('swell_wave_direction'),
        swell_wave_period=values.get('swell_wave_period'),
        wind_wave_height=values.get('wind_wave_height'),
        wind_wave_direction=values.get('wind_wave_direction'),
        wind_wave_period=values.get('wind_wave_period'),
        raw_values={'source_variables': REQUIRED_VARIABLE_MAP, **values},
        quality_flags=quality_flags,
    )


async def ingest_job(db: Session, job: CopernicusIngestionJob) -> dict[str, Any]:
    cfg = load_copernicus_config()
    if cfg.missing_reasons:
        raise RuntimeError('; '.join(cfg.missing_reasons))
    pub = job.publication
    bbox = configured_bbox()
    start, end = temporal_bounds()
    out_dir = cfg.cache_dir / 'raw'
    out_dir.mkdir(parents=True, exist_ok=True)
    temp_file = out_dir / f'copernicus-{pub.id}.tmp.nc'
    final_file = out_dir / f'copernicus-{pub.id}.nc'
    command = build_subset_command(cfg, bbox, start, end, temp_file)
    started = _now()
    env = os.environ.copy()
    if cfg.username:
        env['COPERNICUSMARINE_USERNAME'] = cfg.username
        env['COPERNICUSMARINE_SERVICE_USERNAME'] = cfg.username
    if cfg.password:
        env['COPERNICUSMARINE_PASSWORD'] = cfg.password
        env['COPERNICUSMARINE_SERVICE_PASSWORD'] = cfg.password
    result = await asyncio.to_thread(lambda: subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, check=False))
    if result.returncode != 0:
        detail = (redact((result.stderr or result.stdout or '').strip()) or '')[:3000]
        raise RuntimeError(f'copernicusmarine subset failed with exit {result.returncode}: {detail}')
    if result.stderr:
        safe = redact(result.stderr)
        if safe and 'ERROR' in safe.upper():
            pub.metadata_json = {**(pub.metadata_json or {}), 'toolbox_stderr_tail': safe[-1000:]}
    validation = validate_netcdf(temp_file, cfg.variable_map or REQUIRED_VARIABLE_MAP, bbox)
    checksum = _sha256(temp_file)
    temp_file.replace(final_file)
    now = _now()
    spots = db.query(SurfSpot).all()
    fetch = ProviderFetch(provider_name=PROVIDER, fetched_at=now, latitude=None, longitude=None, status='processing', raw_response={'product_id': cfg.product_id, 'dataset_id': cfg.dataset_id, 'publication_identity': pub.publication_identity, 'variables': list(REQUIRED_VARIABLE_MAP.values()), 'bbox': bbox, 'temporal_bounds': [start.isoformat(), end.isoformat()]}, parsing_errors=None, data_age_seconds=None)
    db.add(fetch)
    db.flush()
    inserted = 0
    ledger_points = []
    for spot in spots:
        points = parse_copernicus_netcdf(final_file, spot.latitude, spot.longitude, cfg.variable_map or REQUIRED_VARIABLE_MAP, PROVIDER)
        for point in points:
            if start <= point.timestamp <= end:
                db.add(MarineForecast(provider_fetch_id=fetch.id, provider_name=PROVIDER, spot_id=spot.id, forecast_time=point.timestamp, fetched_at=now, values=point.values, provider_status='healthy'))
                ledger_points.append(_ledger_point_from_copernicus(spot.id, point))
                inserted += 1
    fetch.status = 'healthy'
    fetch.raw_response = {**(fetch.raw_response or {}), 'raw_file': str(final_file), 'download_size': validation['size'], 'checksum': checksum, 'normalized_records': inserted}
    pub.status = 'healthy' if not validation.get('missing_optional_variables') else 'degraded'
    pub.error = (f"Missing optional variables: {', '.join(validation['missing_optional_variables'])}" if validation.get('missing_optional_variables') else None)
    pub.download_size = validation['size']
    pub.checksum = checksum
    pub.raw_file_path = str(final_file)
    pub.ingestion_completed_at = now
    pub.updated_at = now
    pub.metadata_json = {**(pub.metadata_json or {}), **validation, 'temporal_bounds': [start.isoformat(), end.isoformat()], 'download_duration_seconds': round((now - started).total_seconds(), 1), 'normalized_records': inserted}
    if ledger_writes_enabled():
        try:
            ledger_identity = build_copernicus_publication_identity(cfg.product_id, cfg.dataset_id, pub.model_cycle_time, pub.latest_available_forecast_time, pub.metadata_json)
            ledger_result = write_provider_ledger(
                db,
                ProviderPublicationDescriptor(provider_name=PROVIDER, product_id=cfg.product_id, dataset_id=cfg.dataset_id, publication_identity=ledger_identity, model_cycle_at=pub.model_cycle_time, source_updated_at=pub.updated_at, latest_valid_at=pub.latest_available_forecast_time, detected_at=pub.detected_at, metadata={'legacy_publication_id': pub.id, **(pub.metadata_json or {})}),
                ProviderFetchDescriptor(started_at=started, completed_at=now, status='healthy', download_size_bytes=validation['size'], payload_checksum=checksum, raw_payload_path=str(final_file), metadata={'legacy_provider_fetch_id': fetch.id, 'legacy_job_id': job.id}),
                ForecastRunDescriptor(issued_at=pub.model_cycle_time or start, fetched_at=now, normalized_at=now, geographic_bounds={'bbox': bbox}, temporal_bounds={'start': start.isoformat(), 'end': end.isoformat()}, normalizer_version='copernicus-netcdf-normalizer-v1', normalizer_configuration_hash=hashlib.sha256(json.dumps(cfg.variable_map or REQUIRED_VARIABLE_MAP, sort_keys=True).encode()).hexdigest()),
                ledger_points,
            )
            fetch.metadata_json = {**(fetch.metadata_json or {}), 'ledger_write': ledger_result.__dict__}
        except Exception as exc:
            mark_ledger_failure(db, fetch.id, str(exc), {'stage': 'copernicus_dual_write', 'legacy_job_id': job.id})
            job.status = 'ledger_failed'
            job.last_error = redact(str(exc))[:2000]
            pub.status = 'ledger_failed'
            raise
    job.status = 'succeeded'
    job.completed_at = now
    job.updated_at = now
    calculate_recommendations(db)
    db.commit()
    cleanup_raw_files(db)
    return {'download_size': validation['size'], 'checksum': checksum, 'normalized_records': inserted, 'download_duration_seconds': round((now - started).total_seconds(), 1), 'raw_file': str(final_file)}


def mark_job_failed(db: Session, job: CopernicusIngestionJob, exc: Exception) -> None:
    now = _now()
    message = redact(str(exc))[:2000]
    job.status = 'failed'
    job.last_error = message
    job.updated_at = now
    job.completed_at = now
    job.publication.status = 'failed'
    job.publication.error = message
    job.publication.updated_at = now
    db.commit()


def cleanup_raw_files(db: Session) -> None:
    pubs = db.query(CopernicusPublication).filter(CopernicusPublication.raw_file_path != None).order_by(desc(CopernicusPublication.ingestion_completed_at)).all()
    keep = {p.raw_file_path for p in pubs[:RAW_RETAIN_SUCCESS] if p.raw_file_path}
    for pub in pubs[RAW_RETAIN_SUCCESS:]:
        if pub.raw_file_path and pub.raw_file_path not in keep:
            path = Path(pub.raw_file_path)
            if path.exists():
                path.unlink()
    cutoff = _now() - timedelta(days=FAILED_RETAIN_DAYS)
    cache = load_copernicus_config().cache_dir / 'raw'
    if cache.exists():
        for path in cache.glob('*.tmp.nc'):
            if datetime.fromtimestamp(path.stat().st_mtime, UTC) < cutoff:
                path.unlink()


def latest_status(db: Session) -> dict[str, Any]:
    pub = db.query(CopernicusPublication).order_by(desc(CopernicusPublication.detected_at)).first()
    job = db.query(CopernicusIngestionJob).order_by(desc(CopernicusIngestionJob.created_at)).first()
    cfg = load_copernicus_config()
    return {
        'provider': PROVIDER,
        'product_id': cfg.product_id,
        'dataset_id': cfg.dataset_id,
        'variables': list(REQUIRED_VARIABLE_MAP.values()),
        'bounds': configured_bbox(),
        'latest_detected_publication': pub.publication_identity if pub else None,
        'latest_detected_status': pub.status if pub else None,
        'latest_available_forecast_time': pub.latest_available_forecast_time.isoformat() if pub and pub.latest_available_forecast_time else None,
        'latest_successful_download': pub.ingestion_completed_at.isoformat() if pub and pub.ingestion_completed_at and pub.status in ('healthy', 'degraded') else None,
        'download_size': pub.download_size if pub else None,
        'checksum': pub.checksum if pub else None,
        'current_job_state': job.status if job else None,
        'last_error': redact((job.last_error if job and job.last_error else pub.error if pub else None)),
        'next_scheduled_check_window': 'UTC 00:00-02:59 every 10m, 12:00-14:59 every 10m, reconcile 18:30',
    }
