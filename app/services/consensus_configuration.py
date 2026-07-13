from __future__ import annotations

import hashlib
import json
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
class FieldBehavior:
    required: bool
    tolerance_strong: float | None = None
    tolerance_moderate: float | None = None
    minimum_providers: int = 1
    nearest_time_tolerance_minutes: int = 0
    fallback: str = 'null_when_missing'


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
    required_fields: tuple[str, ...] = ('wave_height', 'wave_direction', 'wave_period', 'wind_speed', 'wind_direction')
    optional_fields: tuple[str, ...] = ('tide_height', 'wind_gust', 'water_temperature', 'current_speed', 'current_direction', 'swell_wave_height', 'swell_wave_direction', 'swell_wave_period', 'wind_wave_height', 'wind_wave_direction', 'wind_wave_period')
    missing_value_rules: dict[str, str] = field(default_factory=dict)
    field_specific_fallback_behavior: dict[str, str] = field(default_factory=dict)
    ipma_corroboration_policy: dict[str, Any] = field(default_factory=dict)
    quality_flag_adjustments: dict[str, float] = field(default_factory=dict)
    spatial_relevance: dict[str, float] = field(default_factory=dict)
    confidence_input_weights: ConfidenceInputWeights = ConfidenceInputWeights()
    labels: dict[str, str] = field(default_factory=dict, compare=False, hash=False)

    def canonical_payload(self) -> dict[str, Any]:
        payload = _stable(asdict(self))
        payload.pop('labels', None)
        return payload

    def configuration_hash(self) -> str:
        body = json.dumps(self.canonical_payload(), sort_keys=True, separators=(',', ':'), ensure_ascii=True)
        return hashlib.sha256(body.encode()).hexdigest()


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
    thresholds = {
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
    for field in DIRECTION_FIELDS:
        thresholds[field] = {'strong': 0.85, 'moderate': 0.55}
    return ConsensusConfiguration(
        engine_version=engine_version or ENGINE_VERSION,
        provider_weights_by_field=weights,
        minimum_providers_per_field={field: 1 for field in CONSENSUS_FIELDS},
        agreement_thresholds=thresholds,
        outlier_thresholds={field: thresholds.get(field, {}).get('moderate', 1.0) * 3 for field in SCALAR_FIELDS},
        missing_value_rules={field: 'preserve_null_and_record' for field in CONSENSUS_FIELDS},
        field_specific_fallback_behavior={field: 'no_cross_field_substitution' for field in CONSENSUS_FIELDS},
        ipma_corroboration_policy={'direct_hourly_weight': 0.0, 'corroboration_only': True},
        quality_flag_adjustments={'missing': 0.0, 'invalid_direction': 0.0, 'out_of_range': 0.0, 'interpolated': 0.75, 'provider_fallback': 0.70, 'schema_warning': 0.80, 'stale_source': 0.50, 'masked_grid_value': 0.50},
        spatial_relevance={'full_until_km': 20.0, 'zero_at_km': 100.0, 'unknown_factor': 0.85},
        labels={'display_name': 'Consensus v1 defaults'},
    )
