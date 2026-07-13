from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any

ENGINE_VERSION = os.getenv('CONSENSUS_ENGINE_VERSION', 'consensus-v1')
CONSENSUS_FIELDS = (
    'wave_height', 'wave_direction', 'wave_period',
    'swell_wave_height', 'swell_wave_direction', 'swell_wave_period',
    'wind_wave_height', 'wind_wave_direction', 'wind_wave_period',
    'wind_speed', 'wind_direction', 'wind_gust',
    'water_temperature', 'current_speed', 'current_direction', 'tide_height',
)
DIRECTION_FIELDS = {'wave_direction', 'swell_wave_direction', 'wind_wave_direction', 'wind_direction', 'current_direction'}
SCALAR_FIELDS = tuple(f for f in CONSENSUS_FIELDS if f not in DIRECTION_FIELDS)


def consensus_engine_enabled() -> bool:
    return os.getenv('CONSENSUS_ENGINE_ENABLED', 'false').lower() == 'true'


@dataclass(frozen=True)
class LinearDecay:
    full_until_hours: float
    zero_at_hours: float


@dataclass(frozen=True)
class OutlierPolicy:
    mode: str = 'downweight'
    downweight_factor: float = 0.25
    minimum_provider_count_for_exclusion: int = 3


@dataclass(frozen=True)
class ConfidenceInputWeights:
    agreement: float = 0.35
    freshness: float = 0.25
    completeness: float = 0.30
    spatial_relevance: float = 0.10


@dataclass(frozen=True)
class ConsensusConfiguration:
    engine_version: str = ENGINE_VERSION
    provider_weights_by_field: dict[str, dict[str, float]] = field(default_factory=dict)
    maximum_provider_age_hours: float = 24.0
    maximum_issue_age_hours: float = 36.0
    source_age_decay: LinearDecay = LinearDecay(full_until_hours=3.0, zero_at_hours=24.0)
    model_cycle_decay: LinearDecay = LinearDecay(full_until_hours=6.0, zero_at_hours=36.0)
    forecast_horizon_decay: LinearDecay = LinearDecay(full_until_hours=24.0, zero_at_hours=96.0)
    minimum_providers_per_field: dict[str, int] = field(default_factory=dict)
    agreement_thresholds: dict[str, dict[str, float]] = field(default_factory=dict)
    outlier_thresholds: dict[str, float] = field(default_factory=dict)
    outlier_policy: OutlierPolicy = OutlierPolicy()
    direction_vector_minimum_magnitude: float = 0.35
    direction_fields: tuple[str, ...] = tuple(sorted(DIRECTION_FIELDS))
    expected_fields: tuple[str, ...] = CONSENSUS_FIELDS
    quality_flag_adjustments: dict[str, float] = field(default_factory=dict)
    spatial_relevance: dict[str, float] = field(default_factory=dict)
    confidence_input_weights: ConfidenceInputWeights = ConfidenceInputWeights()
    labels: dict[str, str] = field(default_factory=dict, compare=False, hash=False)

    def validate(self) -> None:
        known = set(CONSENSUS_FIELDS)
        if not isinstance(self.engine_version, str) or not self.engine_version.strip() or len(self.engine_version) > 80:
            raise ValueError('engine_version must be a non-empty string of at most 80 characters')
        _validate_unique_fields('direction_fields', self.direction_fields, known, allow_empty=True)
        _validate_unique_fields('expected_fields', self.expected_fields, known, allow_empty=False)
        for provider, weights in self.provider_weights_by_field.items():
            if not isinstance(provider, str) or not provider:
                raise ValueError('provider names must be non-empty strings')
            unknown = set(weights) - known
            if unknown:
                raise ValueError(f'provider {provider!r} has unknown fields: {sorted(unknown)}')
            for name, value in weights.items():
                _finite_nonnegative(f'provider weight {provider}.{name}', value)
        _finite_nonnegative('maximum_provider_age_hours', self.maximum_provider_age_hours)
        _finite_nonnegative('maximum_issue_age_hours', self.maximum_issue_age_hours)
        for name in ('source_age_decay', 'model_cycle_decay', 'forecast_horizon_decay'):
            decay = getattr(self, name)
            _finite_nonnegative(f'{name}.full_until_hours', decay.full_until_hours)
            _finite_nonnegative(f'{name}.zero_at_hours', decay.zero_at_hours)
            if decay.zero_at_hours <= decay.full_until_hours:
                raise ValueError(f'{name}.zero_at_hours must exceed full_until_hours')
        unknown_minima = set(self.minimum_providers_per_field) - known
        if unknown_minima:
            raise ValueError(f'unknown minimum-provider fields: {sorted(unknown_minima)}')
        for name, value in self.minimum_providers_per_field.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f'minimum providers for {name} must be a positive integer')
        for name, limits in self.agreement_thresholds.items():
            if name not in known or name in self.direction_fields:
                raise ValueError(f'agreement thresholds only support configured scalar fields: {name}')
            strong = limits.get('strong')
            moderate = limits.get('moderate')
            _finite_nonnegative(f'{name}.strong', strong)
            _finite_nonnegative(f'{name}.moderate', moderate)
            if strong > moderate:
                raise ValueError(f'{name} strong threshold must not exceed moderate threshold')
        for name, value in self.outlier_thresholds.items():
            if name not in known or name in self.direction_fields:
                raise ValueError(f'outlier threshold only supports configured scalar fields: {name}')
            _finite_nonnegative(f'outlier threshold {name}', value)
        if self.outlier_policy.mode not in {'downweight', 'exclude'}:
            raise ValueError('outlier policy mode must be downweight or exclude')
        if not 0 <= self.outlier_policy.downweight_factor <= 1:
            raise ValueError('outlier downweight factor must be in 0..1')
        outlier_minimum = self.outlier_policy.minimum_provider_count_for_exclusion
        if isinstance(outlier_minimum, bool) or not isinstance(outlier_minimum, int) or outlier_minimum < 2:
            raise ValueError('outlier minimum provider count must be an integer of at least 2')
        if not 0 <= self.direction_vector_minimum_magnitude <= 1:
            raise ValueError('direction vector minimum magnitude must be in 0..1')
        for name, value in self.quality_flag_adjustments.items():
            if not isinstance(name, str) or not 0 <= value <= 1:
                raise ValueError(f'quality adjustment {name!r} must be in 0..1')
        required_spatial = {'full_until_km', 'zero_at_km', 'unknown_factor'}
        if set(self.spatial_relevance) != required_spatial:
            raise ValueError(f'spatial_relevance keys must be {sorted(required_spatial)}')
        full = self.spatial_relevance['full_until_km']
        zero = self.spatial_relevance['zero_at_km']
        unknown = self.spatial_relevance['unknown_factor']
        _finite_nonnegative('spatial full_until_km', full)
        _finite_nonnegative('spatial zero_at_km', zero)
        if zero <= full or not 0 <= unknown <= 1:
            raise ValueError('invalid spatial relevance configuration')
        confidence = asdict(self.confidence_input_weights)
        for name, value in confidence.items():
            _finite_nonnegative(f'confidence weight {name}', value)
        if not math.isclose(sum(confidence.values()), 1.0, abs_tol=1e-9):
            raise ValueError('confidence input weights must sum to 1.0')

    def canonical_payload(self) -> dict[str, Any]:
        self.validate()
        payload = _stable(asdict(self))
        payload.pop('labels', None)
        return payload

    def configuration_hash(self) -> str:
        body = json.dumps(self.canonical_payload(), sort_keys=True, separators=(',', ':'), ensure_ascii=True)
        return hashlib.sha256(body.encode()).hexdigest()


def _validate_unique_fields(name: str, values: tuple[str, ...], known: set[str], *, allow_empty: bool) -> None:
    if not allow_empty and not values:
        raise ValueError(f'{name} must not be empty')
    if len(values) != len(set(values)):
        raise ValueError(f'{name} must contain unique fields')
    unknown = set(values) - known
    if unknown:
        raise ValueError(f'{name} contains unknown fields: {sorted(unknown)}')


def _finite_nonnegative(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0:
        raise ValueError(f'{name} must be a finite non-negative number')


def _stable(value: Any) -> Any:
    if is_dataclass(value):
        return _stable(asdict(value))
    if isinstance(value, dict):
        return {str(k): _stable(value[k]) for k in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_stable(v) for v in value]
    if isinstance(value, float):
        return float(format(value, '.12g'))
    return value


def default_consensus_configuration(engine_version: str | None = None) -> ConsensusConfiguration:
    weights = {
        'copernicus-marine': {
            'wave_height': 1.00, 'wave_direction': 1.00, 'wave_period': 1.00,
            'swell_wave_height': 1.00, 'swell_wave_direction': 1.00, 'swell_wave_period': 1.00,
            'wind_wave_height': 1.00, 'wind_wave_direction': 1.00, 'wind_wave_period': 1.00,
            'wind_speed': 0.00, 'wind_direction': 0.00, 'wind_gust': 0.00,
        },
        'mock-open-meteo-marine': {
            'wave_height': 0.75, 'wave_direction': 0.75, 'wave_period': 0.70,
            'swell_wave_height': 0.70, 'swell_wave_direction': 0.70, 'swell_wave_period': 0.65,
            'wind_wave_height': 0.65, 'wind_wave_direction': 0.65, 'wind_wave_period': 0.60,
            'water_temperature': 0.80, 'current_speed': 0.70, 'current_direction': 0.70,
        },
        'open-meteo-marine': {
            'wave_height': 0.75, 'wave_direction': 0.75, 'wave_period': 0.70,
            'swell_wave_height': 0.70, 'swell_wave_direction': 0.70, 'swell_wave_period': 0.65,
            'wind_wave_height': 0.65, 'wind_wave_direction': 0.65, 'wind_wave_period': 0.60,
            'water_temperature': 0.80, 'current_speed': 0.70, 'current_direction': 0.70,
        },
        'mock-open-meteo-weather': {'wind_speed': 1.00, 'wind_direction': 1.00, 'wind_gust': 1.00},
        'open-meteo-weather': {'wind_speed': 1.00, 'wind_direction': 1.00, 'wind_gust': 1.00},
        'ipma': {field: 0.00 for field in CONSENSUS_FIELDS},
    }
    scalar_thresholds = {
        'wave_height': {'strong': 0.15, 'moderate': 0.40},
        'swell_wave_height': {'strong': 0.15, 'moderate': 0.40},
        'wind_wave_height': {'strong': 0.15, 'moderate': 0.40},
        'wave_period': {'strong': 1.0, 'moderate': 2.5},
        'swell_wave_period': {'strong': 1.0, 'moderate': 2.5},
        'wind_wave_period': {'strong': 1.0, 'moderate': 2.5},
        'wind_speed': {'strong': 2.0, 'moderate': 5.0},
        'wind_gust': {'strong': 2.5, 'moderate': 6.0},
        'tide_height': {'strong': 0.10, 'moderate': 0.25},
        'water_temperature': {'strong': 0.5, 'moderate': 1.5},
        'current_speed': {'strong': 0.10, 'moderate': 0.25},
    }
    config = ConsensusConfiguration(
        engine_version=engine_version or ENGINE_VERSION,
        provider_weights_by_field=weights,
        minimum_providers_per_field={field: 1 for field in CONSENSUS_FIELDS},
        agreement_thresholds=scalar_thresholds,
        outlier_thresholds={field: scalar_thresholds.get(field, {}).get('moderate', 1.0) * 3 for field in SCALAR_FIELDS},
        quality_flag_adjustments={'missing': 0.0, 'invalid_direction': 0.0, 'out_of_range': 0.0, 'interpolated': 0.75, 'provider_fallback': 0.70, 'schema_warning': 0.80, 'stale_source': 0.50, 'masked_grid_value': 0.50},
        spatial_relevance={'full_until_km': 20.0, 'zero_at_km': 100.0, 'unknown_factor': 0.85},
        labels={'display_name': 'Consensus v1 defaults'},
    )
    config.validate()
    return config
