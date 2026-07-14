from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass, field

ENGINE_VERSION = os.getenv('SPOT_INTELLIGENCE_ENGINE_VERSION', 'spot-intelligence-v1')


def spot_intelligence_enabled() -> bool:
    """Operational visibility flag only; there is deliberately no automatic hook."""
    return os.getenv('SPOT_INTELLIGENCE_ENABLED', 'false').lower() == 'true'


@dataclass(frozen=True)
class SpotIntelligenceConfiguration:
    engine_version: str = ENGINE_VERSION
    spot_rules_version: str = 'surf-spot-rules-v1'
    acceptable_direction_fit: float = 60.0
    outside_direction_fit: float = 0.0
    range_taper_fraction: float = 1.0
    global_wind_safe_speed: float = 10.0
    global_wind_zero_fit_speed: float = 25.0
    exposure_min: float = 0.5
    exposure_max: float = 1.5
    shelter_min: float = 0.5
    shelter_max: float = 1.5
    period_energy_base_seconds: float = 8.0
    period_energy_cap_seconds: float = 16.0
    period_energy_per_second: float = 0.03
    breaking_lower_multiplier: float = 0.8
    breaking_upper_multiplier: float = 1.25
    breaking_rounding_metres: float = 0.1
    low_consensus_score_threshold: float = 60.0
    labels: dict[str, str] = field(default_factory=dict, compare=False, hash=False)

    def validate(self) -> None:
        for name in ('engine_version', 'spot_rules_version'):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or len(value) > 80:
                raise ValueError(f'{name} must be a non-empty string of at most 80 characters')
        for name in (
            'acceptable_direction_fit', 'outside_direction_fit', 'range_taper_fraction',
            'global_wind_safe_speed', 'global_wind_zero_fit_speed', 'exposure_min',
            'exposure_max', 'shelter_min', 'shelter_max', 'period_energy_base_seconds',
            'period_energy_cap_seconds', 'period_energy_per_second',
            'breaking_lower_multiplier', 'breaking_upper_multiplier',
            'breaking_rounding_metres', 'low_consensus_score_threshold',
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f'{name} must be finite')
        if not 0 <= self.outside_direction_fit <= self.acceptable_direction_fit <= 100:
            raise ValueError('direction fits must satisfy 0 <= outside <= acceptable <= 100')
        if self.range_taper_fraction <= 0:
            raise ValueError('range_taper_fraction must be positive')
        if not 0 <= self.global_wind_safe_speed < self.global_wind_zero_fit_speed:
            raise ValueError('wind thresholds must satisfy 0 <= safe < zero-fit')
        if not 0 < self.exposure_min <= self.exposure_max or not 0 < self.shelter_min <= self.shelter_max:
            raise ValueError('adjustment bounds must be positive and ordered')
        if not 0 <= self.period_energy_base_seconds < self.period_energy_cap_seconds or self.period_energy_per_second < 0:
            raise ValueError('period-energy settings are invalid')
        if not 0 <= self.breaking_lower_multiplier <= self.breaking_upper_multiplier or self.breaking_rounding_metres <= 0:
            raise ValueError('breaking-wave settings are invalid')
        if not 0 <= self.low_consensus_score_threshold <= 100:
            raise ValueError('low_consensus_score_threshold must be in 0..100')

    def canonical_payload(self) -> dict:
        self.validate()
        payload = asdict(self)
        payload.pop('labels', None)
        return _stable(payload)

    def configuration_hash(self) -> str:
        body = json.dumps(self.canonical_payload(), sort_keys=True, separators=(',', ':'), ensure_ascii=True)
        return hashlib.sha256(body.encode()).hexdigest()

    def canonicalized(self) -> 'SpotIntelligenceConfiguration':
        """Return the exact values represented by ``canonical_payload``.

        Calculation and hashing must consume the same values.  In particular,
        this prevents two values on opposite sides of a practical-rounding
        boundary from sharing a hash while producing different output.
        """
        return SpotIntelligenceConfiguration(**self.canonical_payload())


def _stable(value):
    if isinstance(value, dict):
        return {str(key): _stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_stable(item) for item in value]
    if isinstance(value, float):
        return float(format(value, '.12g'))
    return value


def default_spot_intelligence_configuration(engine_version: str | None = None) -> SpotIntelligenceConfiguration:
    config = SpotIntelligenceConfiguration(engine_version=engine_version or ENGINE_VERSION)
    config.validate()
    return config
