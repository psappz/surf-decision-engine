from __future__ import annotations

import gzip
import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..forecast_ledger_models import ForecastRun, ProviderForecastPoint, ProviderPublication
from ..models import ProviderFetch

SCHEMA_VERSION = 'provider-forecast-point-v1'
DEFAULT_NORMALIZER_VERSION = 'provider-ledger-writer-v1'
DEFAULT_NORMALIZER_CONFIGURATION_HASH = 'default-provider-ledger-normalization-v1'


def ledger_writes_enabled() -> bool:
    return os.getenv('PROVIDER_LEDGER_WRITES_ENABLED', 'false').lower() == 'true'


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _now() -> datetime:
    return datetime.now(UTC)


def _hash_dict(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


@dataclass(frozen=True)
class ProviderPublicationDescriptor:
    provider_name: str
    product_id: str | None
    dataset_id: str | None
    publication_identity: str
    model_cycle_at: datetime | None
    source_updated_at: datetime | None
    latest_valid_at: datetime | None
    detected_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderFetchDescriptor:
    started_at: datetime
    completed_at: datetime | None
    status: str = 'processing'
    download_size_bytes: int | None = None
    payload_checksum: str | None = None
    raw_payload_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ForecastRunDescriptor:
    issued_at: datetime
    fetched_at: datetime
    normalized_at: datetime
    geographic_bounds: dict[str, Any] | None
    temporal_bounds: dict[str, Any] | None
    schema_version: str = SCHEMA_VERSION
    normalizer_version: str = DEFAULT_NORMALIZER_VERSION
    normalizer_configuration_hash: str = DEFAULT_NORMALIZER_CONFIGURATION_HASH


@dataclass(frozen=True)
class NormalizedProviderForecastPoint:
    spot_id: int
    sample_point_id: int | str | None
    valid_at: datetime
    wave_height: float | None = None
    wave_direction: float | None = None
    wave_period: float | None = None
    swell_wave_height: float | None = None
    swell_wave_direction: float | None = None
    swell_wave_period: float | None = None
    wind_wave_height: float | None = None
    wind_wave_direction: float | None = None
    wind_wave_period: float | None = None
    wind_speed: float | None = None
    wind_direction: float | None = None
    wind_gust: float | None = None
    water_temperature: float | None = None
    current_speed: float | None = None
    current_direction: float | None = None
    tide_height: float | None = None
    tide_state: str | None = None
    raw_values: dict[str, Any] = field(default_factory=dict)
    quality_flags: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderLedgerWriteResult:
    publication_id: int
    fetch_id: int
    forecast_run_id: int
    forecast_point_count: int
    publication_reused: bool
    forecast_run_reused: bool
    duration_seconds: float


def write_json_raw_payload(provider_name: str, publication_identity: str, payload: Any, root: str | Path | None = None) -> tuple[str, str, int]:
    """Persist small provider JSON payloads as bounded gzip files; credentials/headers must be excluded by caller."""
    base = Path(root or os.getenv('PROVIDER_RAW_PAYLOAD_ROOT', 'data/provider-raw')) / provider_name
    base.mkdir(parents=True, exist_ok=True)
    digest = _hash_dict({'provider': provider_name, 'identity': publication_identity, 'payload': payload})
    path = base / f'{digest[:24]}.json.gz'
    body = json.dumps(payload, sort_keys=True, default=str).encode()
    with gzip.open(path, 'wb') as fh:
        fh.write(body)
    return str(path), hashlib.sha256(body).hexdigest(), path.stat().st_size


def _get_or_create_publication(db: Session, desc: ProviderPublicationDescriptor) -> tuple[ProviderPublication, bool]:
    dataset_id = desc.dataset_id or ''
    existing = db.execute(select(ProviderPublication).where(ProviderPublication.provider_name == desc.provider_name, ProviderPublication.dataset_id == dataset_id, ProviderPublication.publication_identity == desc.publication_identity)).scalar_one_or_none()
    if existing:
        return existing, True
    now = _now()
    row = ProviderPublication(provider_name=desc.provider_name, product_id=desc.product_id, dataset_id=dataset_id, publication_identity=desc.publication_identity, model_cycle_at=_utc(desc.model_cycle_at) if desc.model_cycle_at else None, source_updated_at=_utc(desc.source_updated_at) if desc.source_updated_at else None, latest_valid_at=_utc(desc.latest_valid_at) if desc.latest_valid_at else None, detected_at=_utc(desc.detected_at), status='processing', metadata_json=desc.metadata, created_at=now, updated_at=now)
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.execute(select(ProviderPublication).where(ProviderPublication.provider_name == desc.provider_name, ProviderPublication.dataset_id == dataset_id, ProviderPublication.publication_identity == desc.publication_identity)).scalar_one()
        return existing, True
    return row, False


def _next_attempt_number(db: Session, publication_id: int) -> int:
    current = db.execute(select(func.max(ProviderFetch.attempt_number)).where(ProviderFetch.publication_id == publication_id)).scalar()
    return int(current or 0) + 1


def _create_fetch(db: Session, provider_name: str, publication_id: int, desc: ProviderFetchDescriptor) -> ProviderFetch:
    for _ in range(3):
        attempt = _next_attempt_number(db, publication_id)
        now = _now()
        fetch = ProviderFetch(provider_name=provider_name, fetched_at=_utc(desc.started_at), latitude=None, longitude=None, status=desc.status, raw_response=desc.metadata or None, parsing_errors=None, data_age_seconds=None, publication_id=publication_id, started_at=_utc(desc.started_at), completed_at=_utc(desc.completed_at) if desc.completed_at else None, attempt_number=attempt, download_size_bytes=desc.download_size_bytes, payload_checksum=desc.payload_checksum, raw_payload_path=desc.raw_payload_path, normalized_records_count=0, metadata_json=desc.metadata, created_at=now, updated_at=now)
        db.add(fetch)
        try:
            db.flush()
            return fetch
        except IntegrityError:
            db.rollback()
    raise RuntimeError(f'could not allocate provider fetch attempt for publication {publication_id}')


def write_provider_ledger(db: Session, publication: ProviderPublicationDescriptor, fetch: ProviderFetchDescriptor, forecast_run: ForecastRunDescriptor, points: Iterable[NormalizedProviderForecastPoint]) -> ProviderLedgerWriteResult:
    """Atomically append provider publication/fetch/run/points without changing current runtime read tables."""
    started = perf_counter()
    rows = list(points)
    with db.begin_nested():
        pub, reused_pub = _get_or_create_publication(db, publication)
        fetch_row = _create_fetch(db, publication.provider_name, pub.id, fetch)
        run = db.execute(select(ForecastRun).where(ForecastRun.fetch_id == fetch_row.id, ForecastRun.normalizer_version == forecast_run.normalizer_version, ForecastRun.normalizer_configuration_hash == forecast_run.normalizer_configuration_hash)).scalar_one_or_none()
        reused_run = run is not None
        if run is None:
            run = ForecastRun(provider_name=publication.provider_name, publication_id=pub.id, fetch_id=fetch_row.id, issued_at=_utc(forecast_run.issued_at), fetched_at=_utc(forecast_run.fetched_at), normalized_at=_utc(forecast_run.normalized_at), geographic_bounds_json=forecast_run.geographic_bounds, temporal_bounds_json=forecast_run.temporal_bounds, schema_version=forecast_run.schema_version, normalizer_version=forecast_run.normalizer_version, normalizer_configuration_hash=forecast_run.normalizer_configuration_hash, status='processing', created_at=_now())
            db.add(run)
            db.flush()
        point_rows = []
        for point in rows:
            point_rows.append(ProviderForecastPoint(forecast_run_id=run.id, spot_id=point.spot_id, sample_point_id=str(point.sample_point_id or ''), valid_at=_utc(point.valid_at), wave_height=point.wave_height, wave_direction=point.wave_direction, wave_period=point.wave_period, swell_wave_height=point.swell_wave_height, swell_wave_direction=point.swell_wave_direction, swell_wave_period=point.swell_wave_period, wind_wave_height=point.wind_wave_height, wind_wave_direction=point.wind_wave_direction, wind_wave_period=point.wind_wave_period, wind_speed=point.wind_speed, wind_direction=point.wind_direction, wind_gust=point.wind_gust, water_temperature=point.water_temperature, current_speed=point.current_speed, current_direction=point.current_direction, tide_height=point.tide_height, tide_state=point.tide_state, raw_values_json=point.raw_values, quality_flags_json=point.quality_flags, created_at=_now()))
        if point_rows and not reused_run:
            db.add_all(point_rows)
            db.flush()
        count = 0 if reused_run else len(point_rows)
        fetch_row.status = 'healthy' if fetch.status in ('processing', 'started', 'healthy') else fetch.status
        fetch_row.completed_at = fetch_row.completed_at or _now()
        fetch_row.normalized_records_count = count
        fetch_row.updated_at = _now()
        run.status = 'succeeded'
        pub.status = 'processed'
        pub.updated_at = _now()
    return ProviderLedgerWriteResult(pub.id, fetch_row.id, run.id, count, reused_pub, reused_run, round(perf_counter() - started, 4))


def mark_ledger_failure(db: Session, fetch_id: int | None, message: str, metadata: dict[str, Any] | None = None) -> None:
    """Record visible ledger failure metadata when a dual-write attempt fails after legacy persistence."""
    if fetch_id is None:
        return
    fetch = db.get(ProviderFetch, fetch_id)
    if not fetch:
        return
    fetch.status = 'ledger_failed'
    fetch.error_code = 'ledger_write_failed'
    fetch.error_message = message[:1000]
    fetch.metadata_json = {**(fetch.metadata_json or {}), **(metadata or {})}
    fetch.updated_at = _now()
    db.flush()
