from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Iterable

from ..models import SurfSpot
from .consensus_safety import redact_text
from .spot_intelligence_configuration import _stable

RULE_FIELDS = (
    'is_active_for_recommendations',
    'preferred_swell_direction_min', 'preferred_swell_direction_max',
    'acceptable_swell_direction_min', 'acceptable_swell_direction_max',
    'preferred_swell_height_min', 'preferred_swell_height_max',
    'maximum_safe_swell_height_for_profile',
    'preferred_period_min', 'preferred_period_max',
    'preferred_wind_direction_min', 'preferred_wind_direction_max',
    'preferred_tide_min', 'preferred_tide_max', 'tide_preference',
    'exposure_factor', 'shelter_factor', 'hazards', 'base_confidence',
)


@dataclass(frozen=True)
class SpotRulesSnapshot:
    version: str
    spots: tuple[dict[str, Any], ...]

    def canonical_payload(self) -> dict[str, Any]:
        return _stable({'version': self.version, 'spots': list(self.spots)})

    def canonical_json(self) -> str:
        return json.dumps(self.canonical_payload(), sort_keys=True, separators=(',', ':'), ensure_ascii=True)

    def rules_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()

    def for_spot(self, spot_id: int) -> dict[str, Any]:
        return next(item for item in self.spots if item['spot_id'] == spot_id)


def build_spot_rules_snapshot(spots: Iterable[SurfSpot], *, version: str) -> SpotRulesSnapshot:
    rows = tuple(sorted((_snapshot_spot(spot) for spot in spots), key=lambda row: row['spot_id']))
    if not rows:
        raise ValueError('calculation scope contains no SurfSpot rows')
    if len({row['spot_id'] for row in rows}) != len(rows):
        raise ValueError('spot rules snapshot contains duplicate spot IDs')
    return SpotRulesSnapshot(version, rows)


def _snapshot_spot(spot: SurfSpot) -> dict[str, Any]:
    raw = {name: getattr(spot, name) for name in RULE_FIELDS}
    effective: dict[str, Any] = {'is_active_for_recommendations': bool(raw['is_active_for_recommendations'])}
    issues: list[dict[str, str]] = []
    directions = (
        ('preferred_swell_direction_min', 'preferred_swell_direction_max'),
        ('acceptable_swell_direction_min', 'acceptable_swell_direction_max'),
        ('preferred_wind_direction_min', 'preferred_wind_direction_max'),
    )
    for lo_name, hi_name in directions:
        pair = _pair(raw, lo_name, hi_name, directions=True)
        effective[lo_name], effective[hi_name] = pair
        if pair == (None, None) and (raw[lo_name] is not None or raw[hi_name] is not None):
            issues.append({'code': 'INVALID_DIRECTION_RANGE', 'field': lo_name.rsplit('_', 1)[0]})
    ranges = (
        ('preferred_swell_height_min', 'preferred_swell_height_max', True),
        ('preferred_period_min', 'preferred_period_max', True),
        ('preferred_tide_min', 'preferred_tide_max', False),
    )
    for lo_name, hi_name, nonnegative in ranges:
        pair = _pair(raw, lo_name, hi_name, nonnegative=nonnegative)
        effective[lo_name], effective[hi_name] = pair
        if pair == (None, None) and (raw[lo_name] is not None or raw[hi_name] is not None):
            issues.append({'code': 'INVALID_ORDERED_RANGE', 'field': lo_name.rsplit('_', 1)[0]})
    maximum = _number(raw['maximum_safe_swell_height_for_profile'], nonnegative=True)
    effective['maximum_safe_swell_height_for_profile'] = maximum
    if maximum is None and raw['maximum_safe_swell_height_for_profile'] is not None:
        issues.append({'code': 'INVALID_MAXIMUM_SAFE_HEIGHT', 'field': 'maximum_safe_swell_height_for_profile'})
    for name in ('exposure_factor', 'shelter_factor'):
        value = _number(raw[name], positive=True)
        effective[name] = value
        if value is None and raw[name] is not None:
            issues.append({'code': f'INVALID_{name.upper()}', 'field': name})
    base = _number(raw['base_confidence'])
    effective['base_confidence'] = base if base is not None and 0 <= base <= 1 else None
    if effective['base_confidence'] is None and raw['base_confidence'] is not None:
        issues.append({'code': 'INVALID_BASE_CONFIDENCE', 'field': 'base_confidence'})
    tide = raw['tide_preference'].strip().lower() if isinstance(raw['tide_preference'], str) else None
    effective['tide_preference'] = tide if tide in {'low', 'mid', 'high', 'all', 'any'} else None
    if tide and effective['tide_preference'] is None:
        issues.append({'code': 'INVALID_TIDE_PREFERENCE', 'field': 'tide_preference'})
    hazard = redact_text(raw['hazards'], max_length=500).strip() if raw['hazards'] else None
    effective['hazards'] = hazard
    # Invalid raw values are represented safely so they remain hash-visible without
    # leaking arbitrary objects or non-finite JSON tokens.
    raw_audit = {name: _audit_value(value) for name, value in raw.items()}
    return {'spot_id': int(spot.id), 'raw_rules': raw_audit, 'effective_rules': effective, 'metadata_issues': issues}


def _pair(raw, lo_name, hi_name, *, directions=False, nonnegative=False):
    lo = _number(raw[lo_name], nonnegative=nonnegative)
    hi = _number(raw[hi_name], nonnegative=nonnegative)
    if lo is None or hi is None:
        return None, None
    if directions:
        if not 0 <= lo < 360 or not 0 <= hi < 360:
            return None, None
    elif lo > hi:
        return None, None
    return lo, hi


def _number(value, *, nonnegative=False, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    value = float(value)
    if nonnegative and value < 0 or positive and value <= 0:
        return None
    return float(format(value, '.12g'))


def _audit_value(value):
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return _number(value)
    return redact_text(value, max_length=500)
