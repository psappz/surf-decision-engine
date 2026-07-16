from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, replace
from typing import Any

ENGINE_VERSION = os.getenv('SPOT_SCORING_ENGINE_VERSION', 'spot-scoring-v1')
_VERSION_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$')
_PROFILE_VERSION = 'surfer-profiles-v1'


def _version(name: str, value: object) -> str:
    if not isinstance(value, str) or not _VERSION_PATTERN.fullmatch(value):
        raise ValueError(f'{name} must be a valid version identifier of at most 80 characters')
    return value


def _number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f'{name} must be a finite number')
    normalized = float(format(float(value), '.12g'))
    # JSON has two spellings for zero but they are not distinct scoring values.
    return 0.0 if normalized == 0 else normalized


def _optional_number(name: str, value: object) -> float | None:
    return None if value is None else _number(name, value)


def _digest(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256(body.encode()).hexdigest()


def canonical_payload_hash(payload: dict[str, Any]) -> str:
    """Hash an already validated canonical payload."""
    if not isinstance(payload, dict):
        raise ValueError('canonical payload must be an object')
    return _digest(payload)


@dataclass(frozen=True)
class SpotScoringConfiguration:
    """Validated scoring mechanics, without a score formula or classification policy."""

    engine_version: str = ENGINE_VERSION
    score_minimum: float = 0.0
    score_maximum: float = 100.0
    component_minimum: float = 0.0
    component_maximum: float = 100.0
    maximum_penalty: float = 100.0

    def effective_values(self) -> dict[str, float]:
        """Values future calculation code must consume and the hash covers."""
        _version('engine_version', self.engine_version)
        values = {
            'score_minimum': _number('score_minimum', self.score_minimum),
            'score_maximum': _number('score_maximum', self.score_maximum),
            'component_minimum': _number('component_minimum', self.component_minimum),
            'component_maximum': _number('component_maximum', self.component_maximum),
            'maximum_penalty': _number('maximum_penalty', self.maximum_penalty),
        }
        if not 0 <= values['score_minimum'] < values['score_maximum'] <= 100:
            raise ValueError('score bounds must be strictly ordered within 0..100')
        if not 0 <= values['component_minimum'] < values['component_maximum'] <= 100:
            raise ValueError('component bounds must be strictly ordered within 0..100')
        if not 0 <= values['maximum_penalty'] <= 100:
            raise ValueError('maximum_penalty must be within 0..100')
        return values

    def validate(self) -> None:
        self.effective_values()

    def canonical_payload(self) -> dict[str, float]:
        # Engine version is recorded separately on the run. Hash only behavior.
        return self.effective_values()

    def configuration_hash(self) -> str:
        return _digest(self.canonical_payload())

    def canonicalized(self) -> 'SpotScoringConfiguration':
        return SpotScoringConfiguration(engine_version=_version('engine_version', self.engine_version), **self.effective_values())


@dataclass(frozen=True)
class SurferProfileSnapshot:
    """Immutable effective profile values stored beside a human-readable version."""

    profile_name: str
    profile_version: str
    preferred_breaking_wave_min: float | None
    preferred_breaking_wave_max: float | None
    maximum_safe_breaking_wave: float | None
    preferred_period_min: float | None
    preferred_period_max: float | None

    def effective_values(self) -> dict[str, Any]:
        if self.profile_name not in KNOWN_SURFER_PROFILES:
            raise ValueError(f'unknown surfer profile: {self.profile_name!r}')
        _version('profile_version', self.profile_version)
        values = {
            'preferred_breaking_wave_min': _optional_number('preferred_breaking_wave_min', self.preferred_breaking_wave_min),
            'preferred_breaking_wave_max': _optional_number('preferred_breaking_wave_max', self.preferred_breaking_wave_max),
            'maximum_safe_breaking_wave': _optional_number('maximum_safe_breaking_wave', self.maximum_safe_breaking_wave),
            'preferred_period_min': _optional_number('preferred_period_min', self.preferred_period_min),
            'preferred_period_max': _optional_number('preferred_period_max', self.preferred_period_max),
        }
        _ordered_optional_bounds('breaking-wave', values['preferred_breaking_wave_min'], values['preferred_breaking_wave_max'])
        _ordered_optional_bounds('period', values['preferred_period_min'], values['preferred_period_max'])
        for field in ('preferred_breaking_wave_min', 'preferred_breaking_wave_max', 'maximum_safe_breaking_wave', 'preferred_period_min', 'preferred_period_max'):
            if values[field] is not None and values[field] < 0:
                raise ValueError(f'{field} must be non-negative')
        wave_max = values['preferred_breaking_wave_max']
        safe = values['maximum_safe_breaking_wave']
        if wave_max is not None and safe is not None and safe < wave_max:
            raise ValueError('maximum_safe_breaking_wave must not be below the preferred maximum')
        return values

    def validate(self) -> None:
        self.effective_values()

    def canonical_payload(self) -> dict[str, Any]:
        # Name/version are run identity metadata, not behavior. This means
        # labels or a version rename cannot silently alter the behavior hash.
        return self.effective_values()

    def surfer_profile_hash(self) -> str:
        return _digest(self.canonical_payload())

    @property
    def version(self) -> str:
        return _version('profile_version', self.profile_version)

    @property
    def profile_hash(self) -> str:
        return self.surfer_profile_hash()

    def canonicalized(self) -> 'SurferProfileSnapshot':
        return replace(self, profile_version=self.version, **self.effective_values())


def _ordered_optional_bounds(name: str, lower: float | None, upper: float | None) -> None:
    if (lower is None) != (upper is None):
        raise ValueError(f'{name} bounds must both be set or both be null')
    if lower is not None and upper is not None and upper <= lower:
        raise ValueError(f'{name} bounds must be strictly ordered')


# These are exact physical-range values from the existing selectable
# proficiency categories. Legacy hazard penalties and advanced-fit points are
# deliberately omitted: no approved mapping exists from those values into the
# new scoring model. No total formula consumes this snapshot in this slice.
_PROFILE_VALUES: dict[str, dict[str, float | None]] = {
    'beginner': dict(preferred_breaking_wave_min=.35, preferred_breaking_wave_max=.9, maximum_safe_breaking_wave=1.25, preferred_period_min=6, preferred_period_max=11),
    'rookie': dict(preferred_breaking_wave_min=.45, preferred_breaking_wave_max=1.15, maximum_safe_breaking_wave=1.55, preferred_period_min=7, preferred_period_max=12),
    'intermediate': dict(preferred_breaking_wave_min=.65, preferred_breaking_wave_max=1.65, maximum_safe_breaking_wave=2.25, preferred_period_min=8, preferred_period_max=14),
    'advanced': dict(preferred_breaking_wave_min=None, preferred_breaking_wave_max=None, maximum_safe_breaking_wave=None, preferred_period_min=None, preferred_period_max=None),
    'pro': dict(preferred_breaking_wave_min=.9, preferred_breaking_wave_max=2.5, maximum_safe_breaking_wave=3.8, preferred_period_min=10, preferred_period_max=18),
}
KNOWN_SURFER_PROFILES = frozenset(_PROFILE_VALUES)


def surfer_profile_snapshot(profile_name: str, *, profile_version: str = _PROFILE_VERSION) -> SurferProfileSnapshot:
    if not isinstance(profile_name, str) or profile_name not in _PROFILE_VALUES:
        raise ValueError(f'unknown surfer profile: {profile_name!r}')
    snapshot = SurferProfileSnapshot(
        profile_name=profile_name,
        profile_version=_version('profile_version', profile_version),
        **_PROFILE_VALUES[profile_name],
    )
    snapshot.validate()
    return snapshot.canonicalized()


def default_spot_scoring_configuration(engine_version: str | None = None) -> SpotScoringConfiguration:
    config = SpotScoringConfiguration(
        engine_version=ENGINE_VERSION if engine_version is None else engine_version
    ).canonicalized()
    config.validate()
    return config
