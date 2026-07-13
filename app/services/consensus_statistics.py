from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import median
from typing import Any

from .consensus_configuration import ConsensusConfiguration, LinearDecay


@dataclass(frozen=True)
class WeightedValue:
    provider_name: str
    value: float
    effective_weight: float
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


def to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def linear_decay(age_hours: float, policy: LinearDecay) -> float:
    age = max(0.0, float(age_hours))
    if age <= policy.full_until_hours:
        return 1.0
    if age >= policy.zero_at_hours:
        return 0.0
    return (policy.zero_at_hours - age) / (policy.zero_at_hours - policy.full_until_hours)


def validate_value(field: str, value: Any, direction_fields: tuple[str, ...]) -> tuple[float | None, str | None]:
    if value is None:
        return None, 'missing'
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, 'non_numeric'
    if not math.isfinite(number):
        return None, 'nonfinite'
    if field in direction_fields:
        return number % 360.0, None
    if field in {'wave_height', 'swell_wave_height', 'wind_wave_height', 'wave_period', 'swell_wave_period', 'wind_wave_period', 'wind_speed', 'wind_gust', 'current_speed'} and number < 0:
        return None, 'negative'
    return number, None


def quality_adjustment(flags: dict[str, Any] | None, field: str, configuration: ConsensusConfiguration) -> tuple[float, list[str]]:
    if not isinstance(flags, dict):
        return 1.0, []
    matched: list[Any] = []
    if field in flags:
        matched.append(flags[field])
    for key in sorted(flags, key=str):
        if key == field:
            continue
        if str(key).startswith(f'{field}.') or str(key).startswith(f'{field}_'):
            matched.append(flags[key])
    reasons: list[str] = []
    factor = 1.0
    for raw in matched:
        entries = raw if isinstance(raw, (list, tuple, set)) else [raw]
        for entry in entries:
            reason = str(entry)
            reasons.append(reason)
            factor *= float(configuration.quality_flag_adjustments.get(reason, 1.0))
    return max(0.0, min(1.0, factor)), reasons


def freshness_factor(cutoff: datetime, issued_at: datetime, fetched_at: datetime, valid_at: datetime, configuration: ConsensusConfiguration) -> tuple[float, dict[str, float]]:
    cutoff, issued, fetched, valid = map(to_utc, (cutoff, issued_at, fetched_at, valid_at))
    source_age = max(0.0, (cutoff - fetched).total_seconds() / 3600.0)
    cycle_age = max(0.0, (cutoff - issued).total_seconds() / 3600.0)
    horizon = max(0.0, (valid - issued).total_seconds() / 3600.0)
    source = linear_decay(source_age, configuration.source_age_decay)
    cycle = linear_decay(cycle_age, configuration.model_cycle_decay)
    horizon_factor = linear_decay(horizon, configuration.forecast_horizon_decay)
    return source * cycle * horizon_factor, {'source_age_hours': source_age, 'model_cycle_age_hours': cycle_age, 'forecast_horizon_hours': horizon, 'source_age_factor': source, 'model_cycle_factor': cycle, 'forecast_horizon_factor': horizon_factor}


def scalar_consensus(field: str, values: list[WeightedValue], configuration: ConsensusConfiguration) -> FieldConsensus:
    minimum = configuration.minimum_providers_per_field.get(field, 1)
    providers = {item.provider_name for item in values if item.effective_weight > 0}
    if len(providers) < minimum:
        excluded = tuple(_insufficient(item, minimum, len(providers)) for item in values)
        return FieldConsensus(None, 0.0, _weighted_component(values, 'freshness_factor'), _weighted_component(values, 'spatial_relevance_factor'), (), excluded, 'insufficient_distinct_providers')
    active = [item for item in values if item.effective_weight > 0]
    if not active:
        return FieldConsensus(None, 0.0, 0.0, 0.0, (), (), 'no_eligible_values')
    center = _weighted_median(active)
    threshold = configuration.outlier_thresholds.get(field, math.inf)
    adjusted: list[tuple[WeightedValue, float, str | None]] = []
    distinct_count = len({item.provider_name for item in active})
    for item in active:
        weight = item.effective_weight
        adjustment = None
        if distinct_count >= configuration.outlier_policy.minimum_provider_count_for_exclusion and abs(item.value - center) > threshold:
            adjustment = 'robust_outlier'
            weight = 0.0 if configuration.outlier_policy.mode == 'exclude' else weight * configuration.outlier_policy.downweight_factor
        adjusted.append((item, weight, adjustment))
    surviving = [(item, weight, reason) for item, weight, reason in adjusted if weight > 0]
    removed = [(item, weight, reason) for item, weight, reason in adjusted if weight <= 0]
    surviving_providers = {item.provider_name for item, _, _ in surviving}
    if len(surviving_providers) < minimum:
        excluded = tuple(
            {**item.provenance, 'value': item.value, 'effective_weight': 0.0, 'excluded': True, 'exclusion_reason': reason or 'insufficient_distinct_providers', 'required_provider_count': minimum, 'actual_provider_count': len(surviving_providers)}
            for item, _, reason in adjusted
        )
        return FieldConsensus(None, 0.0, 0.0, 0.0, (), excluded, 'insufficient_distinct_providers')
    denominator = sum(weight for _, weight, _ in surviving)
    if denominator <= 0:
        excluded = tuple({**item.provenance, 'value': item.value, 'effective_weight': 0.0, 'excluded': True, 'exclusion_reason': reason or 'zero_effective_weight'} for item, _, reason in adjusted)
        return FieldConsensus(None, 0.0, 0.0, 0.0, (), excluded, 'no_weight_after_outlier_policy')
    result = sum(item.value * weight for item, weight, _ in surviving) / denominator
    contributors = tuple({**item.provenance, 'value': item.value, 'effective_weight': weight, 'excluded': False, 'adjustment_reason': reason} for item, weight, reason in surviving)
    excluded = tuple({**item.provenance, 'value': item.value, 'effective_weight': 0.0, 'excluded': True, 'exclusion_reason': reason or 'zero_effective_weight', 'adjustment_reason': reason} for item, _, reason in removed)
    weighted_active = [WeightedValue(item.provider_name, item.value, weight, item.provenance) for item, weight, _ in surviving]
    agreement = _scalar_agreement(field, [item.value for item, _, _ in surviving], configuration)
    return FieldConsensus(result, agreement, _weighted_component(weighted_active, 'freshness_factor'), _weighted_component(weighted_active, 'spatial_relevance_factor'), contributors, excluded)


def direction_consensus(field: str, values: list[WeightedValue], configuration: ConsensusConfiguration) -> FieldConsensus:
    minimum = configuration.minimum_providers_per_field.get(field, 1)
    active = [item for item in values if item.effective_weight > 0]
    providers = {item.provider_name for item in active}
    if len(providers) < minimum:
        excluded = tuple(_insufficient(item, minimum, len(providers)) for item in active)
        return FieldConsensus(None, 0.0, _weighted_component(active, 'freshness_factor'), _weighted_component(active, 'spatial_relevance_factor'), (), excluded, 'insufficient_distinct_providers')
    denominator = sum(item.effective_weight for item in active)
    if denominator <= 0:
        return FieldConsensus(None, 0.0, 0.0, 0.0, (), (), 'no_eligible_values')
    x = sum(math.cos(math.radians(item.value % 360.0)) * item.effective_weight for item in active)
    y = sum(math.sin(math.radians(item.value % 360.0)) * item.effective_weight for item in active)
    magnitude = math.hypot(x, y) / denominator
    contributors = tuple({**item.provenance, 'value': item.value % 360.0, 'effective_weight': item.effective_weight, 'excluded': False} for item in active)
    if magnitude < configuration.direction_vector_minimum_magnitude:
        return FieldConsensus(None, magnitude * 100.0, _weighted_component(active, 'freshness_factor'), _weighted_component(active, 'spatial_relevance_factor'), contributors, (), 'directional_cancellation')
    direction = math.degrees(math.atan2(y, x)) % 360.0
    return FieldConsensus(direction, magnitude * 100.0, _weighted_component(active, 'freshness_factor'), _weighted_component(active, 'spatial_relevance_factor'), contributors, ())


def _insufficient(item: WeightedValue, required: int, actual: int) -> dict[str, Any]:
    return {**item.provenance, 'value': item.value, 'effective_weight': 0.0, 'excluded': True, 'exclusion_reason': 'insufficient_distinct_providers', 'required_provider_count': required, 'actual_provider_count': actual}


def _weighted_median(values: list[WeightedValue]) -> float:
    ordered = sorted(values, key=lambda item: item.value)
    total = sum(item.effective_weight for item in ordered)
    running = 0.0
    for item in ordered:
        running += item.effective_weight
        if running >= total / 2:
            return item.value
    return median(item.value for item in ordered)


def _scalar_agreement(field: str, values: list[float], configuration: ConsensusConfiguration) -> float:
    if len(values) < 2:
        return 100.0
    spread = max(values) - min(values)
    threshold = configuration.agreement_thresholds.get(field, {'strong': 0.1, 'moderate': 1.0})
    strong, moderate = threshold['strong'], threshold['moderate']
    if spread <= strong:
        return 100.0
    if spread >= moderate:
        return max(0.0, 50.0 * (1.0 - (spread - moderate) / max(moderate, 1e-9)))
    return 100.0 - 50.0 * ((spread - strong) / max(moderate - strong, 1e-9))


def _weighted_component(values: list[WeightedValue], name: str) -> float:
    denominator = sum(item.effective_weight for item in values)
    if denominator <= 0:
        return 0.0
    return 100.0 * sum(item.effective_weight * float(item.provenance.get(name, 0.0)) for item in values) / denominator
