from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import median
from typing import Any

from .consensus_configuration import ConsensusConfiguration, DIRECTION_FIELDS


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def linear_decay(age_hours: float, full_until_hours: float, zero_at_hours: float) -> float:
    if age_hours <= full_until_hours:
        return 1.0
    if age_hours >= zero_at_hours:
        return 0.0
    return clamp(1.0 - ((age_hours - full_until_hours) / (zero_at_hours - full_until_hours)))


@dataclass(frozen=True)
class WeightedValue:
    provider_name: str
    value: float
    weight: float
    provenance: dict[str, Any]


@dataclass(frozen=True)
class FieldConsensus:
    value: float | None
    agreement_score: float
    freshness_score: float
    spatial_relevance_score: float
    contributors: tuple[dict[str, Any], ...]
    excluded: tuple[dict[str, Any], ...]
    warning: str | None = None


def normalize_direction(value: float) -> float:
    return float(value % 360.0)


def validate_value(field: str, value: Any) -> tuple[float | None, str | None]:
    if value is None:
        return None, 'missing'
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, 'not_numeric'
    if math.isnan(number) or math.isinf(number):
        return None, 'not_finite'
    if field in DIRECTION_FIELDS:
        return normalize_direction(number), None
    if field in {'wave_height', 'swell_wave_height', 'wind_wave_height', 'wave_period', 'swell_wave_period', 'wind_wave_period', 'wind_speed', 'wind_gust', 'current_speed'} and number < 0:
        return None, 'negative_value'
    return number, None


def quality_adjustment(flags: dict | None, field: str, cfg: ConsensusConfiguration) -> tuple[float, list[str]]:
    if not flags:
        return 1.0, []
    reasons: list[str] = []
    factor = 1.0
    candidates = []
    if field in flags:
        candidates.append(flags[field])
    for key, val in flags.items():
        if key == field or key.startswith(field + '.') or key.startswith(field + '_'):
            candidates.append(val)
    for raw in candidates:
        vals = raw if isinstance(raw, list) else [raw]
        for v in vals:
            reason = str(v)
            reasons.append(reason)
            factor *= float(cfg.quality_flag_adjustments.get(reason, 1.0))
    return clamp(factor), reasons


def freshness_factor(forecast_cutoff_at: datetime, issued_at: datetime, fetched_at: datetime, valid_at: datetime, cfg: ConsensusConfiguration) -> tuple[float, dict[str, float]]:
    cutoff = to_utc(forecast_cutoff_at); issued = to_utc(issued_at); fetched = to_utc(fetched_at); valid = to_utc(valid_at)
    source_age_hours = max(0.0, (cutoff - fetched).total_seconds() / 3600.0)
    model_cycle_age_hours = max(0.0, (cutoff - issued).total_seconds() / 3600.0)
    horizon_hours = max(0.0, (valid - issued).total_seconds() / 3600.0)
    source = linear_decay(source_age_hours, cfg.source_age_decay.full_until_hours, cfg.source_age_decay.zero_at_hours)
    model = linear_decay(model_cycle_age_hours, cfg.model_cycle_decay.full_until_hours, cfg.model_cycle_decay.zero_at_hours)
    horizon = linear_decay(horizon_hours, cfg.forecast_horizon_decay.full_until_hours, cfg.forecast_horizon_decay.zero_at_hours)
    return clamp(source * model * horizon), {'source_age_hours': source_age_hours, 'model_cycle_age_hours': model_cycle_age_hours, 'forecast_horizon_hours': horizon_hours, 'source_age_factor': source, 'model_cycle_factor': model, 'forecast_horizon_factor': horizon}


def scalar_consensus(field: str, values: list[WeightedValue], cfg: ConsensusConfiguration) -> FieldConsensus:
    if not values:
        return FieldConsensus(None, 0.0, 0.0, 0.0, (), (), 'no_eligible_inputs')
    center = _weighted_median([(v.value, v.weight) for v in values])
    threshold = cfg.outlier_thresholds.get(field)
    final: list[WeightedValue] = []
    excluded: list[dict[str, Any]] = []
    for v in values:
        adjusted_weight = v.weight
        reason = None
        if threshold is not None and len(values) >= cfg.outlier_policy.minimum_provider_count_for_exclusion and abs(v.value - center) > threshold:
            reason = f'outlier_deviation_gt_{threshold:g}'
            if cfg.outlier_policy.mode == 'exclude':
                p = dict(v.provenance); p.update({'excluded': True, 'exclusion_reason': reason})
                excluded.append(p); continue
            adjusted_weight *= cfg.outlier_policy.downweight_factor
        p = dict(v.provenance); p.update({'effective_weight': adjusted_weight, 'excluded': False, 'exclusion_reason': reason})
        final.append(WeightedValue(v.provider_name, v.value, adjusted_weight, p))
    if not final or sum(v.weight for v in final) <= 0:
        return FieldConsensus(None, 0.0, _avg([v.provenance.get('freshness_factor', 0) for v in values]), _avg([v.provenance.get('spatial_relevance_factor', 0) for v in values]), tuple(v.provenance for v in values), tuple(excluded), 'zero_effective_weight')
    result = sum(v.value * v.weight for v in final) / sum(v.weight for v in final)
    dev = sum(abs(v.value - result) * v.weight for v in final) / sum(v.weight for v in final)
    agreement = _agreement_score(field, dev, cfg)
    return FieldConsensus(result, agreement, _weighted_average_meta(final, 'freshness_factor'), _weighted_average_meta(final, 'spatial_relevance_factor'), tuple(v.provenance for v in final), tuple(excluded), None)


def direction_consensus(field: str, values: list[WeightedValue], cfg: ConsensusConfiguration) -> FieldConsensus:
    if not values:
        return FieldConsensus(None, 0.0, 0.0, 0.0, (), (), 'no_eligible_inputs')
    total_weight = sum(v.weight for v in values)
    if total_weight <= 0:
        return FieldConsensus(None, 0.0, 0.0, 0.0, tuple(v.provenance for v in values), (), 'zero_effective_weight')
    x = sum(math.cos(math.radians(v.value)) * v.weight for v in values)
    y = sum(math.sin(math.radians(v.value)) * v.weight for v in values)
    magnitude = math.hypot(x, y) / total_weight
    contributors = []
    for v in values:
        p = dict(v.provenance); p.update({'effective_weight': v.weight, 'excluded': False, 'resultant_vector_magnitude': magnitude})
        contributors.append(p)
    if magnitude < cfg.direction_vector_minimum_magnitude:
        return FieldConsensus(None, magnitude * 100.0, _weighted_average_meta(values, 'freshness_factor'), _weighted_average_meta(values, 'spatial_relevance_factor'), tuple(contributors), (), 'directional_cancellation')
    direction = normalize_direction(math.degrees(math.atan2(y, x)))
    return FieldConsensus(direction, magnitude * 100.0, _weighted_average_meta(values, 'freshness_factor'), _weighted_average_meta(values, 'spatial_relevance_factor'), tuple(contributors), (), None)


def _weighted_median(values: list[tuple[float, float]]) -> float:
    values = sorted(values, key=lambda item: item[0])
    total = sum(w for _, w in values)
    if total <= 0:
        return median([v for v, _ in values])
    acc = 0.0
    for value, weight in values:
        acc += weight
        if acc >= total / 2.0:
            return value
    return values[-1][0]


def _agreement_score(field: str, deviation: float, cfg: ConsensusConfiguration) -> float:
    thresholds = cfg.agreement_thresholds.get(field, {})
    strong = thresholds.get('strong')
    moderate = thresholds.get('moderate')
    if strong is None or moderate is None:
        return max(0.0, 100.0 - deviation * 10.0)
    if deviation <= strong:
        return 100.0
    if deviation <= moderate:
        return 70.0 + 30.0 * (moderate - deviation) / (moderate - strong)
    return max(0.0, 70.0 * (1.0 - min(1.0, (deviation - moderate) / max(moderate, 1e-9))))


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _weighted_average_meta(values: list[WeightedValue], key: str) -> float:
    total = sum(v.weight for v in values)
    if total <= 0:
        return 0.0
    return clamp(sum(float(v.provenance.get(key, 0.0)) * v.weight for v in values) / total) * 100.0
