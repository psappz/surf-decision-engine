from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..forecast_ledger_models import ForecastRun, ProviderForecastPoint, ProviderPublication
from ..models import SurfSpot
from .consensus_configuration import CONSENSUS_FIELDS, ConsensusConfiguration
from .consensus_statistics import freshness_factor, quality_adjustment, to_utc, validate_value


@dataclass(frozen=True)
class SelectedProviderInput:
    provider_name: str
    field: str
    value: float
    effective_weight: float
    provenance: dict[str, Any]


@dataclass(frozen=True)
class SelectionResult:
    inputs_by_spot_time_field: dict[tuple[int, datetime, str], list[SelectedProviderInput]]
    excluded_by_spot_time_field: dict[tuple[int, datetime, str], list[dict[str, Any]]]
    provider_names: tuple[str, ...]
    point_count: int
    warnings: tuple[str, ...]


def timestamp_available(value: datetime | None, cutoff: datetime) -> bool:
    """Legacy null timestamps are conservatively unavailable; equality is eligible."""
    return value is not None and to_utc(value) <= to_utc(cutoff)


def select_consensus_inputs(
    db: Session,
    *,
    cutoff: datetime,
    valid_from: datetime,
    valid_until: datetime,
    spot_ids: tuple[int, ...] | None,
    configuration: ConsensusConfiguration,
) -> SelectionResult:
    cutoff, valid_from, valid_until = to_utc(cutoff), to_utc(valid_from), to_utc(valid_until)
    statement = (
        select(ProviderForecastPoint, ForecastRun, ProviderPublication, SurfSpot)
        .join(ForecastRun, ForecastRun.id == ProviderForecastPoint.forecast_run_id)
        .outerjoin(ProviderPublication, ProviderPublication.id == ForecastRun.publication_id)
        .join(SurfSpot, SurfSpot.id == ProviderForecastPoint.spot_id)
        .where(
            ForecastRun.status == 'succeeded',
            ForecastRun.issued_at.is_not(None),
            ForecastRun.fetched_at.is_not(None),
            ForecastRun.normalized_at.is_not(None),
            ProviderForecastPoint.created_at.is_not(None),
            ForecastRun.issued_at <= cutoff,
            ForecastRun.fetched_at <= cutoff,
            ForecastRun.normalized_at <= cutoff,
            ProviderForecastPoint.created_at <= cutoff,
            ProviderForecastPoint.valid_at >= valid_from,
            ProviderForecastPoint.valid_at <= valid_until,
        )
        .order_by(ProviderForecastPoint.spot_id, ProviderForecastPoint.valid_at, ForecastRun.provider_name, ForecastRun.fetched_at.desc(), ForecastRun.normalized_at.desc(), ForecastRun.id.desc(), ProviderForecastPoint.id)
    )
    if spot_ids:
        statement = statement.where(ProviderForecastPoint.spot_id.in_(spot_ids))
    rows = db.execute(statement).all()

    grouped_runs: dict[tuple[int, datetime, str, int], list[tuple[ProviderForecastPoint, ForecastRun, ProviderPublication | None, SurfSpot]]] = {}
    for point, run, publication, spot in rows:
        key = (point.spot_id, to_utc(point.valid_at), run.provider_name, run.id)
        grouped_runs.setdefault(key, []).append((point, run, publication, spot))

    latest_groups: dict[tuple[int, datetime, str], list[tuple[ProviderForecastPoint, ForecastRun, ProviderPublication | None, SurfSpot]]] = {}
    latest_rank: dict[tuple[int, datetime, str], tuple[datetime, datetime, int]] = {}
    for (spot_id, valid_at, provider, run_id), group in grouped_runs.items():
        run = group[0][1]
        rank = (to_utc(run.fetched_at), to_utc(run.normalized_at), run_id)
        key = (spot_id, valid_at, provider)
        if key not in latest_rank or rank > latest_rank[key]:
            latest_rank[key] = rank
            latest_groups[key] = group

    selected: dict[tuple[int, datetime, str], list[SelectedProviderInput]] = {}
    excluded: dict[tuple[int, datetime, str], list[dict[str, Any]]] = {}
    providers: set[str] = set()
    point_ids: set[int] = set()

    for (spot_id, valid_at, provider), group in sorted(latest_groups.items(), key=lambda item: item[0]):
        run = group[0][1]
        publication = group[0][2]
        source_age = max(0.0, (cutoff - to_utc(run.fetched_at)).total_seconds() / 3600.0)
        issue_age = max(0.0, (cutoff - to_utc(run.issued_at)).total_seconds() / 3600.0)
        for field in CONSENSUS_FIELDS:
            key = (spot_id, valid_at, field)
            candidates: list[tuple[tuple[float, float, str, int], SelectedProviderInput]] = []
            rejected = excluded.setdefault(key, [])
            for point, _, _, spot in group:
                raw = getattr(point, field, None)
                value, invalid_reason = validate_value(field, raw, configuration.direction_fields)
                base_weight = float(configuration.provider_weights_by_field.get(provider, {}).get(field, 0.0))
                quality_factor, quality_reasons = quality_adjustment(point.quality_flags_json, field, configuration)
                fresh, fresh_details = freshness_factor(cutoff, run.issued_at, run.fetched_at, point.valid_at, configuration)
                spatial_factor, distance_km = spatial_relevance_details(spot, point, configuration)
                provenance = {
                    'provider_name': provider,
                    'provider_publication_id': publication.id if publication else None,
                    'provider_fetch_id': run.fetch_id,
                    'forecast_run_id': run.id,
                    'forecast_point_id': point.id,
                    'sample_point_id': point.sample_point_id,
                    'issued_at': to_utc(run.issued_at).isoformat(),
                    'fetched_at': to_utc(run.fetched_at).isoformat(),
                    'normalized_at': to_utc(run.normalized_at).isoformat(),
                    'point_created_at': to_utc(point.created_at).isoformat(),
                    'valid_at': valid_at.isoformat(),
                    'raw_value': raw,
                    'base_weight': base_weight,
                    **fresh_details,
                    'quality_factor': quality_factor,
                    'quality_reasons': quality_reasons,
                    'spatial_relevance_factor': spatial_factor,
                    'distance_km': distance_km,
                    'schema_version': run.schema_version,
                    'normalizer_version': run.normalizer_version,
                    'normalizer_configuration_hash': run.normalizer_configuration_hash,
                    'interpolation_method': 'exact_valid_at_only',
                }
                reason = None
                if invalid_reason:
                    reason = invalid_reason
                elif source_age > configuration.maximum_provider_age_hours:
                    reason = 'maximum_provider_age_exceeded'
                elif issue_age > configuration.maximum_issue_age_hours:
                    reason = 'maximum_issue_age_exceeded'
                elif base_weight <= 0:
                    reason = 'zero_provider_field_weight'
                elif quality_factor <= 0:
                    reason = 'quality_excluded'
                elif fresh <= 0:
                    reason = 'freshness_zero'
                elif spatial_factor <= 0:
                    reason = 'spatial_relevance_zero'
                effective_weight = base_weight * quality_factor * fresh * spatial_factor
                if reason or value is None or effective_weight <= 0:
                    rejected.append({**provenance, 'effective_weight': 0.0, 'excluded': True, 'exclusion_reason': reason or 'zero_effective_weight'})
                    continue
                selected_provenance = {**provenance, 'effective_weight': effective_weight, 'excluded': False}
                candidate = SelectedProviderInput(provider, field, value, effective_weight, selected_provenance)
                distance_sort = distance_km if distance_km is not None else math.inf
                rank = (spatial_factor, -distance_sort, point.sample_point_id or '', -point.id)
                candidates.append((rank, candidate))
            if candidates:
                candidates.sort(key=lambda item: item[0], reverse=True)
                winner = candidates[0][1]
                selected.setdefault(key, []).append(winner)
                providers.add(provider)
                point_ids.add(winner.provenance['forecast_point_id'])
                for _, loser in candidates[1:]:
                    rejected.append({**loser.provenance, 'excluded': True, 'exclusion_reason': 'less_spatially_relevant_sample', 'effective_weight': 0.0})
    selected = {key: value for key, value in selected.items() if value}
    excluded = {key: value for key, value in excluded.items() if value}
    return SelectionResult(selected, excluded, tuple(sorted(providers)), len(point_ids), ())


def spatial_relevance_details(spot: SurfSpot, point: ProviderForecastPoint, configuration: ConsensusConfiguration) -> tuple[float, float | None]:
    raw = point.raw_values_json if isinstance(point.raw_values_json, dict) else {}
    lat = raw.get('selected_latitude', raw.get('latitude'))
    lon = raw.get('selected_longitude', raw.get('longitude'))
    spatial = configuration.spatial_relevance
    if lat is None or lon is None:
        return float(spatial['unknown_factor']), None
    try:
        coordinates = tuple(float(value) for value in (spot.latitude, spot.longitude, lat, lon))
        if not all(math.isfinite(value) for value in coordinates):
            raise ValueError('nonfinite coordinate')
        spot_lat, spot_lon, selected_lat, selected_lon = coordinates
        if not (-90 <= selected_lat <= 90 and -180 <= selected_lon <= 180):
            raise ValueError('coordinate outside geographic range')
        distance = haversine_km(spot_lat, spot_lon, selected_lat, selected_lon)
    except (TypeError, ValueError, OverflowError):
        return float(spatial['unknown_factor']), None
    full, zero = float(spatial['full_until_km']), float(spatial['zero_at_km'])
    if distance <= full:
        return 1.0, distance
    if distance >= zero:
        return 0.0, distance
    return (zero - distance) / (zero - full), distance


def spatial_relevance(spot: SurfSpot, point: ProviderForecastPoint, configuration: ConsensusConfiguration) -> float:
    return spatial_relevance_details(spot, point, configuration)[0]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))
