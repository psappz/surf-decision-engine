from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

COPERNICUS_PROVIDER = 'copernicus-marine'
OPEN_METEO_MARINE_PROVIDER = 'open-meteo-marine'
OPEN_METEO_WEATHER_PROVIDER = 'open-meteo-weather'
IPMA_PROVIDER = 'ipma-open-data'


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _digest(payload: dict[str, Any], length: int = 20) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:length]


def bounded_content_hash(payload: Any, length: int = 20) -> str:
    """Return a deterministic bounded hash for provider payload identity fallback without storing secrets."""
    return _digest({'payload': payload}, length=length)


def build_copernicus_publication_identity(product_id: str, dataset_id: str, model_cycle_at: datetime | None, latest_valid_at: datetime | None, metadata: dict[str, Any] | None = None) -> str:
    """Build a Copernicus identity from model-cycle/catalogue inputs; fetched_at is intentionally excluded."""
    metadata_fingerprint = _digest(metadata or {}, 16) if metadata else 'no-metadata'
    payload = {
        'provider': COPERNICUS_PROVIDER,
        'product_id': product_id,
        'dataset_id': dataset_id,
        'model_cycle_at': _utc_iso(model_cycle_at),
        'latest_valid_at': _utc_iso(latest_valid_at),
        'metadata_fingerprint': metadata_fingerprint,
    }
    return f"copernicus:{product_id}:{dataset_id}:{payload['model_cycle_at'] or 'unknown-cycle'}:{payload['latest_valid_at'] or 'unknown-latest'}:{metadata_fingerprint}"


def build_open_meteo_publication_identity(provider_name: str, latitude: float | None, longitude: float | None, start: datetime, end: datetime, issue_time: datetime | None = None, response_metadata: dict[str, Any] | None = None, content: Any | None = None) -> str:
    """Build Open-Meteo identity from request scope plus issue/update metadata or a bounded content hash fallback."""
    payload = {
        'provider': provider_name,
        'lat': round(latitude, 5) if latitude is not None else None,
        'lon': round(longitude, 5) if longitude is not None else None,
        'start': _utc_iso(start),
        'end': _utc_iso(end),
        'issue_time': _utc_iso(issue_time),
        'metadata': response_metadata or {},
        'content_hash': bounded_content_hash(content) if issue_time is None and content is not None else None,
    }
    return f"open-meteo:{provider_name}:{_digest(payload, 24)}"


def build_ipma_publication_identity(feed_type: str, endpoint: str, data_update: str | None, forecast_date: str | None = None, location_id: int | str | None = None, category: str | None = None) -> str:
    """Build an IPMA identity per feed/location/date; daily ranges are not expanded into fake hourly cycles."""
    payload = {
        'provider': IPMA_PROVIDER,
        'feed_type': feed_type,
        'endpoint': endpoint,
        'data_update': data_update,
        'forecast_date': forecast_date,
        'location_id': str(location_id) if location_id is not None else None,
        'category': category,
    }
    return f"ipma:{feed_type}:{location_id or 'all'}:{forecast_date or 'unknown-date'}:{_digest(payload, 18)}"
