from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..forecast_ledger_models import ForecastRun, ProviderForecastPoint, ProviderPublication
from ..models import SurfSpot
from .consensus_configuration import CONSENSUS_FIELDS, ConsensusConfiguration, DIRECTION_FIELDS
from .consensus_statistics import freshness_factor, quality_adjustment, to_utc, validate_value


@dataclass(frozen=True)
class SelectedProviderInput:
    provider_name: str
    field_name: str
    value: float
    point: ProviderForecastPoint
    run: ForecastRun
    publication: ProviderPublication | None
    effective_weight: float
    base_weight: float
    freshness_factor: float
    freshness_details: dict[str, float]
    quality_factor: float
    spatial_relevance_factor: float
    time_offset_minutes: float
    provenance: dict[str, Any]


@dataclass(frozen=True)
class SelectionResult:
    inputs_by_spot_time_field: dict[tuple[int, datetime, str], list[SelectedProviderInput]]
    valid_times: tuple[datetime, ...]
    provider_names: tuple[str, ...]
    point_count: int
    warnings: tuple[str, ...]


def select_consensus_inputs(db: Session, *, forecast_cutoff_at: datetime, valid_from: datetime, valid_until: datetime, spot_ids: tuple[int, ...] | None, configuration: ConsensusConfiguration) -> SelectionResult:
    cutoff = to_utc(forecast_cutoff_at)
    vf = to_utc(valid_from); vu = to_utc(valid_until)
    spot_stmt = select(SurfSpot).where(SurfSpot.is_active_for_recommendations == True)  # noqa: E712
    if spot_ids:
        spot_stmt = spot_stmt.where(SurfSpot.id.in_(spot_ids))
    spots = {s.id: s for s in db.execute(spot_stmt.order_by(SurfSpot.id)).scalars().all()}
    if not spots:
        return SelectionResult({}, (), (), 0, ('no_spots_selected',))
    stmt = (
        select(ProviderForecastPoint, ForecastRun, ProviderPublication)
        .join(ForecastRun, ProviderForecastPoint.forecast_run_id == ForecastRun.id)
        .outerjoin(ProviderPublication, ForecastRun.publication_id == ProviderPublication.id)
        .where(
            ProviderForecastPoint.spot_id.in_(spots.keys()),
            ProviderForecastPoint.valid_at >= vf,
            ProviderForecastPoint.valid_at <= vu,
            ForecastRun.fetched_at <= cutoff,
            ForecastRun.issued_at <= cutoff,
            ForecastRun.status.in_(('succeeded', 'completed')),
        )
        .order_by(ProviderForecastPoint.spot_id, ProviderForecastPoint.valid_at, ForecastRun.provider_name, ForecastRun.fetched_at.desc(), ForecastRun.id.desc())
    )
    rows = db.execute(stmt).all()
    latest_by_provider: dict[tuple[int, datetime, str], tuple[ProviderForecastPoint, ForecastRun, ProviderPublication | None]] = {}
    warnings: list[str] = []
    for point, run, pub in rows:
        valid = to_utc(point.valid_at)
        provider = run.provider_name
        key = (point.spot_id, valid, provider)
        current = latest_by_provider.get(key)
        if current is None or (to_utc(run.fetched_at), run.id, point.sample_point_id or '') > (to_utc(current[1].fetched_at), current[1].id, current[0].sample_point_id or ''):
            latest_by_provider[key] = (point, run, pub)
    out: dict[tuple[int, datetime, str], list[SelectedProviderInput]] = {}
    providers = set()
    for point, run, pub in latest_by_provider.values():
        spot = spots.get(point.spot_id)
        if not spot:
            continue
        providers.add(run.provider_name)
        for field in CONSENSUS_FIELDS:
            raw = getattr(point, field, None)
            value, invalid_reason = validate_value(field, raw)
            base_weight = float(configuration.provider_weights_by_field.get(run.provider_name, {}).get(field, 0.0))
            if run.provider_name == 'ipma' and configuration.ipma_corroboration_policy.get('corroboration_only', True):
                base_weight = 0.0
            quality_factor, quality_reasons = quality_adjustment(point.quality_flags_json, field, configuration)
            fresh, fresh_details = freshness_factor(cutoff, run.issued_at, run.fetched_at, point.valid_at, configuration)
            spatial = spatial_relevance(spot, point, configuration)
            excluded_reason = None
            if invalid_reason:
                excluded_reason = invalid_reason
            elif base_weight <= 0:
                excluded_reason = 'zero_provider_field_weight'
            elif quality_factor <= 0:
                excluded_reason = 'quality_flag_excluded'
            elif fresh <= 0:
                excluded_reason = 'stale_or_outside_horizon'
            provenance = {
                'provider_name': run.provider_name,
                'provider_publication_id': run.publication_id,
                'provider_fetch_id': run.fetch_id,
                'forecast_run_id': run.id,
                'forecast_point_id': point.id,
                'issued_at': to_utc(run.issued_at).isoformat(),
                'fetched_at': to_utc(run.fetched_at).isoformat(),
                'valid_at': to_utc(point.valid_at).isoformat(),
                'raw_provider_value': raw,
                'base_weight': base_weight,
                'freshness_factor': fresh,
                'freshness_details': fresh_details,
                'horizon_factor': fresh_details.get('forecast_horizon_factor'),
                'quality_adjustment': quality_factor,
                'quality_reasons': quality_reasons,
                'spatial_relevance_factor': spatial,
                'sample_point_id': point.sample_point_id,
                'schema_version': run.schema_version,
                'normalizer_version': run.normalizer_version,
                'normalizer_configuration_hash': run.normalizer_configuration_hash,
                'publication_identity': pub.publication_identity if pub else None,
                'time_offset_minutes': 0.0,
                'interpolation_method': 'exact',
                'excluded': excluded_reason is not None,
                'exclusion_reason': excluded_reason,
            }
            if excluded_reason or value is None:
                continue
            effective_weight = base_weight * fresh * quality_factor * spatial
            if effective_weight <= 0:
                continue
            selected = SelectedProviderInput(run.provider_name, field, value, point, run, pub, effective_weight, base_weight, fresh, fresh_details, quality_factor, spatial, 0.0, provenance)
            out.setdefault((point.spot_id, to_utc(point.valid_at), field), []).append(selected)
    valid_times = sorted({key[1] for key in out})
    return SelectionResult(out, tuple(valid_times), tuple(sorted(providers)), len(latest_by_provider), tuple(warnings))


def spatial_relevance(spot: SurfSpot, point: ProviderForecastPoint, cfg: ConsensusConfiguration) -> float:
    raw = point.raw_values_json or {}
    lat = _first_number(raw, ('selected_latitude', 'selected_lat', 'grid_latitude', 'latitude', 'requested_latitude'))
    lon = _first_number(raw, ('selected_longitude', 'selected_lon', 'grid_longitude', 'longitude', 'requested_longitude'))
    if lat is None or lon is None or spot.latitude is None or spot.longitude is None:
        return float(cfg.spatial_relevance.get('unknown_factor', 0.85))
    distance = haversine_km(float(spot.latitude), float(spot.longitude), lat, lon)
    full = float(cfg.spatial_relevance.get('full_until_km', 20.0))
    zero = float(cfg.spatial_relevance.get('zero_at_km', 100.0))
    if distance <= full:
        return 1.0
    if distance >= zero:
        return 0.0
    return max(0.0, 1.0 - (distance - full) / (zero - full))


def _first_number(data: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if key in data and data[key] is not None:
            try:
                return float(data[key])
            except (TypeError, ValueError):
                return None
    selected = data.get('selected_grid') if isinstance(data.get('selected_grid'), dict) else {}
    for key in keys:
        if key in selected and selected[key] is not None:
            try:
                return float(selected[key])
            except (TypeError, ValueError):
                return None
    return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))
