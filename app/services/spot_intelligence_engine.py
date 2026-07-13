from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..forecast_ledger_models import ConsensusForecastPoint, ConsensusRun
from ..models import SurfSpot
from ..repositories.spot_assessment_repository import (
    create_spot_assessment_points, create_spot_assessment_run,
    find_equivalent_completed_assessment, list_spot_assessment_points_for_run,
    mark_spot_assessment_run_status, next_spot_assessment_recalculation_sequence,
)
from .consensus_safety import bounded_json, redact_text
from .spot_intelligence_configuration import SpotIntelligenceConfiguration, default_spot_intelligence_configuration
from .spot_intelligence_rules import SpotRulesSnapshot, build_spot_rules_snapshot

FORMULA_VERSION = 'spot-assessment-formulas-v1'


@dataclass(frozen=True)
class SpotAssessmentRequest:
    consensus_run_id: int
    spot_ids: tuple[int, ...] | None
    engine_version: str
    configuration: SpotIntelligenceConfiguration
    force_recalculation: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class SpotAssessmentResult:
    assessment_run_id: int | None
    consensus_run_id: int
    points_written: int
    spots_processed: int
    status: str
    spot_rules_hash: str
    configuration_hash: str
    calculation_scope_hash: str
    warnings: tuple[str, ...]
    duration_seconds: float


class SpotIntelligenceEngine:
    def __init__(self, db: Session):
        self.db = db

    def calculate(self, request: SpotAssessmentRequest) -> SpotAssessmentResult:
        started = perf_counter()
        request = _validated_request(request)
        # Input run state is validated before any assessment write.
        consensus_run = self.db.get(ConsensusRun, request.consensus_run_id)
        if consensus_run is None:
            raise ValueError(f'consensus run {request.consensus_run_id} does not exist')
        if consensus_run.status != 'completed':
            raise ValueError(f'consensus run {request.consensus_run_id} is {consensus_run.status}, not completed')
        config_hash = request.configuration.configuration_hash()
        points = self._select_points(request)
        if not points:
            raise ValueError('completed consensus run has no points in the selected scope')
        spot_ids = tuple(sorted({point.spot_id for point in points}))
        spots = list(self.db.scalars(select(SurfSpot).where(SurfSpot.id.in_(spot_ids)).order_by(SurfSpot.id)))
        found = {spot.id for spot in spots}
        if found != set(spot_ids):
            raise ValueError(f'missing SurfSpot rows for IDs {sorted(set(spot_ids) - found)}')
        snapshot = build_spot_rules_snapshot(spots, version=request.configuration.spot_rules_version)
        rules_hash = snapshot.rules_hash()
        scope = {'spot_ids': list(request.spot_ids) if request.spot_ids else None, 'consensus_point_ids': [point.id for point in points]}
        scope_hash = _hash(scope)
        warnings = tuple(sorted({issue['code'] for row in snapshot.spots for issue in row['metadata_issues']}))
        if not request.dry_run and not request.force_recalculation:
            existing = find_equivalent_completed_assessment(
                self.db, consensus_run_id=consensus_run.id, rules_hash=rules_hash,
                engine_version=request.engine_version, configuration_hash=config_hash, scope_hash=scope_hash,
            )
            if existing:
                existing_points = list_spot_assessment_points_for_run(self.db, existing.id)
                return SpotAssessmentResult(existing.id, consensus_run.id, 0, len({p.spot_id for p in existing_points}), 'reused', rules_hash, config_hash, scope_hash, warnings, perf_counter() - started)
        if request.dry_run:
            rows = self._build_points(None, points, snapshot, request.configuration, consensus_run)
            return SpotAssessmentResult(None, consensus_run.id, len(rows), len(spot_ids), 'dry_run', rules_hash, config_hash, scope_hash, warnings, perf_counter() - started)
        metadata_items = max(64, len(points) + 8, len(snapshot.spots) + 8)
        metadata = bounded_json({
            'calculation_scope': scope,
            'calculation_scope_hash': scope_hash,
            'consensus': {'run_id': consensus_run.id, 'engine_version': consensus_run.consensus_engine_version, 'configuration_hash': consensus_run.configuration_hash},
            'spot_rules_snapshot': snapshot.canonical_payload(),
            'spot_rules_hash': rules_hash,
            'engine_version': request.engine_version,
            'configuration_hash': config_hash,
            'configuration_snapshot': request.configuration.canonical_payload(),
            'formula_version': FORMULA_VERSION,
            'shadow_mode': True,
            'warnings': list(warnings),
        }, max_items=metadata_items, max_bytes=131_072)
        recalculation_sequence = next_spot_assessment_recalculation_sequence(
            self.db, consensus_run_id=consensus_run.id, rules_hash=rules_hash,
            engine_version=request.engine_version, configuration_hash=config_hash,
            scope_hash=scope_hash, force=request.force_recalculation,
        )
        run = create_spot_assessment_run(
            self.db, consensus_run_id=consensus_run.id, calculated_at=datetime.now(UTC),
            spot_rules_version=snapshot.version, spot_rules_hash=rules_hash,
            spot_intelligence_engine_version=request.engine_version, configuration_hash=config_hash,
            calculation_scope_hash=scope_hash, recalculation_sequence=recalculation_sequence,
            status='running', metadata_json=metadata,
        )
        self.db.commit()
        run_id = run.id
        stage = 'build_points'
        try:
            rows = self._build_points(run_id, points, snapshot, request.configuration, consensus_run)
            stage = 'insert_points'
            create_spot_assessment_points(self.db, rows)
            stage = 'complete_run'
            completed_metadata = dict(metadata)
            completed_metadata.update({'status': 'completed', 'points_written': len(rows), 'duration_seconds': perf_counter() - started})
            mark_spot_assessment_run_status(self.db, run_id, 'completed', metadata_json=bounded_json(completed_metadata, max_items=metadata_items, max_bytes=131_072))
            self.db.commit()
            return SpotAssessmentResult(run_id, consensus_run.id, len(rows), len(spot_ids), 'completed', rules_hash, config_hash, scope_hash, warnings, perf_counter() - started)
        except Exception as exc:
            self.db.rollback()
            failed = dict(metadata)
            failed.update({'status': 'failed', 'failure_stage': redact_text(stage, max_length=40), 'duration_seconds': perf_counter() - started})
            try:
                mark_spot_assessment_run_status(self.db, run_id, 'failed', error_message=_safe_error(exc), metadata_json=bounded_json(failed, max_items=metadata_items, max_bytes=131_072))
                self.db.commit()
            except Exception:
                self.db.rollback()
            raise

    def _select_points(self, request: SpotAssessmentRequest) -> list[ConsensusForecastPoint]:
        stmt = select(ConsensusForecastPoint).where(ConsensusForecastPoint.consensus_run_id == request.consensus_run_id)
        if request.spot_ids:
            stmt = stmt.where(ConsensusForecastPoint.spot_id.in_(request.spot_ids))
        stmt = stmt.order_by(ConsensusForecastPoint.valid_at, ConsensusForecastPoint.spot_id, ConsensusForecastPoint.id)
        return list(self.db.scalars(stmt))

    def _build_points(self, run_id: int | None, points: list[ConsensusForecastPoint], snapshot: SpotRulesSnapshot, config: SpotIntelligenceConfiguration, consensus_run: ConsensusRun) -> list[dict[str, Any]]:
        return [_assess_point(run_id, point, snapshot.for_spot(point.spot_id), snapshot.rules_hash(), config, consensus_run) for point in points]


def _assess_point(run_id, point, snapshot_row, rules_hash, config, consensus_run):
    rules = snapshot_row['effective_rules']
    uncertainty: list[dict[str, Any]] = []
    hazards: list[dict[str, Any]] = []
    for issue in snapshot_row['metadata_issues']:
        uncertainty.append({'code': 'INVALID_SPOT_METADATA_FALLBACK', 'detail': issue})
        hazards.append({'code': 'INVALID_SPOT_METADATA', 'field': issue['field']})
    if not rules['is_active_for_recommendations']:
        uncertainty.append({'code': 'INACTIVE_OR_OBSERVATION_ONLY_SPOT'})
    height, height_source = _primary(point.swell_wave_height, point.wave_height)
    direction, direction_source = _primary(point.swell_wave_direction, point.wave_direction)
    period, period_source = _primary(point.swell_wave_period, point.wave_period)
    for name, value, source in (('height', height, height_source), ('direction', direction, direction_source), ('period', period, period_source)):
        if value is None:
            uncertainty.append({'code': 'MISSING_INPUT', 'field': name})
        elif source.startswith('total_wave'):
            uncertainty.append({'code': 'TOTAL_WAVE_FALLBACK', 'field': name, 'source': source})
    direction_fit = circular_direction_fit(direction, rules['preferred_swell_direction_min'], rules['preferred_swell_direction_max'], rules['acceptable_swell_direction_min'], rules['acceptable_swell_direction_max'], config)
    height_fit = range_fit(height, rules['preferred_swell_height_min'], rules['preferred_swell_height_max'], taper_fraction=config.range_taper_fraction)
    maximum = rules['maximum_safe_swell_height_for_profile']
    if height is not None and maximum is not None and height > maximum:
        height_fit = 0.0
        hazards.append({'code': 'SWELL_HEIGHT_ABOVE_SPOT_MAXIMUM', 'value_m': _round(height), 'threshold_m': maximum})
    period_fit = range_fit(period, rules['preferred_period_min'], rules['preferred_period_max'], taper_fraction=config.range_taper_fraction)
    wind_direction_fit = preferred_direction_fit(point.wind_direction, rules['preferred_wind_direction_min'], rules['preferred_wind_direction_max'])
    if _direction(point.wind_direction) is None:
        uncertainty.append({'code': 'MISSING_INPUT' if point.wind_direction is None else 'INVALID_INPUT', 'field': 'wind_direction'})
    wind_speed_fit = wind_speed_fit_global(point.wind_speed, config)
    valid_wind_speed = _finite(point.wind_speed)
    if valid_wind_speed is None or valid_wind_speed < 0:
        uncertainty.append({'code': 'MISSING_INPUT' if point.wind_speed is None else 'INVALID_INPUT', 'field': 'wind_speed'})
    else:
        uncertainty.append({'code': 'GLOBAL_WIND_SPEED_RULE_USED', 'safe_threshold': config.global_wind_safe_speed, 'zero_fit_threshold': config.global_wind_zero_fit_speed, 'reason': 'SurfSpot has no wind-speed rule fields'})
        if valid_wind_speed > config.global_wind_zero_fit_speed:
            hazards.append({'code': 'WIND_SPEED_ABOVE_GLOBAL_THRESHOLD', 'value': _round(valid_wind_speed), 'threshold': config.global_wind_zero_fit_speed})
    tide_fit = range_fit(point.tide_height, rules['preferred_tide_min'], rules['preferred_tide_max'], taper_fraction=config.range_taper_fraction)
    if point.tide_height is None:
        uncertainty.append({'code': 'MISSING_INPUT', 'field': 'tide_height'})
    if rules['tide_preference'] not in (None, 'all', 'any'):
        uncertainty.append({'code': 'TIDE_STATE_UNAVAILABLE', 'preference': rules['tide_preference'], 'note': 'preference retained; no tide state invented'})
    for factor_name, rule_name in (('swell_direction', 'preferred_swell_direction_min'), ('swell_height', 'preferred_swell_height_min'), ('period', 'preferred_period_min'), ('wind_direction', 'preferred_wind_direction_min'), ('tide', 'preferred_tide_min')):
        if rules[rule_name] is None:
            uncertainty.append({'code': 'MISSING_SPOT_RULE', 'factor': factor_name})
    exposure, exposure_fallback = _bounded_factor(rules['exposure_factor'], config.exposure_min, config.exposure_max)
    shelter, shelter_fallback = _bounded_factor(rules['shelter_factor'], config.shelter_min, config.shelter_max)
    if exposure_fallback:
        uncertainty.append({'code': 'ADJUSTMENT_FALLBACK', 'field': 'exposure_factor', 'effective': exposure})
    if shelter_fallback:
        uncertainty.append({'code': 'ADJUSTMENT_FALLBACK', 'field': 'shelter_factor', 'effective': shelter})
    breaking_min, breaking_max, breaking_details = provisional_breaking_range(height, direction_fit, period, exposure, shelter, tide_fit, config)
    uncertainty.append({'code': 'PROVISIONAL_BREAKING_TRANSFORM', 'method': 'model-derived', 'formula_version': FORMULA_VERSION})
    if rules['hazards']:
        hazards.append({'code': 'STATIC_SPOT_HAZARD', 'supporting_context': rules['hazards']})
    consensus_uncertainty = {}
    for name in ('agreement_score', 'freshness_score', 'completeness_score', 'confidence_input_score'):
        value = _finite(getattr(point, name))
        consensus_uncertainty[name] = value
        if value is None:
            uncertainty.append({'code': 'MISSING_CONSENSUS_QUALITY_INPUT', 'field': name})
        elif value < config.low_consensus_score_threshold:
            uncertainty.append({'code': 'LOW_CONSENSUS_QUALITY_INPUT', 'field': name, 'value': value})
    spatial = _finite((point.calculation_details_json or {}).get('spatial_relevance_score')) if isinstance(point.calculation_details_json, dict) else None
    consensus_uncertainty['spatial_relevance_score'] = spatial
    if spatial is None:
        uncertainty.append({'code': 'MISSING_CONSENSUS_QUALITY_INPUT', 'field': 'spatial_relevance_score'})
    details = bounded_json({
        'formula_version': FORMULA_VERSION,
        'method_label': 'model-derived provisional spot assessment',
        'engine_configuration': {'engine_version': config.engine_version, 'configuration_hash': config.configuration_hash(), 'snapshot': config.canonical_payload()},
        'consensus_provenance': {'point_id': point.id, 'run_id': consensus_run.id, 'engine_version': consensus_run.consensus_engine_version, 'configuration_hash': consensus_run.configuration_hash},
        'spot_rules_reference': {'spot_id': point.spot_id, 'spot_rules_hash': rules_hash, 'snapshot_entry': snapshot_row},
        'inputs': {'height': height, 'height_source': height_source, 'direction': direction, 'direction_source': direction_source, 'period': period, 'period_source': period_source, 'wind_speed': _finite(point.wind_speed), 'wind_direction': _finite(point.wind_direction), 'tide_height': _finite(point.tide_height)},
        'fits': {'swell_direction_fit': direction_fit, 'swell_height_fit': height_fit, 'period_fit': period_fit, 'wind_direction_fit': wind_direction_fit, 'wind_speed_fit': wind_speed_fit, 'tide_fit': tide_fit},
        'transformations': {'exposure_adjustment': exposure, 'shelter_adjustment': shelter, 'breaking_wave': breaking_details},
        'consensus_uncertainty_inputs': consensus_uncertainty,
        'warnings': uncertainty,
        'prohibited_outputs_absent': ['total_surf_score', 'ranking', 'go_no_go', 'classification', 'daypart', 'recommendation', 'final_confidence'],
    }, max_items=64, max_bytes=131_072)
    return {
        'assessment_run_id': run_id or 0, 'spot_id': point.spot_id, 'valid_at': point.valid_at,
        'swell_direction_fit': direction_fit, 'swell_height_fit': height_fit, 'period_fit': period_fit,
        'wind_direction_fit': wind_direction_fit, 'wind_speed_fit': wind_speed_fit, 'tide_fit': tide_fit,
        'exposure_adjustment': exposure, 'shelter_adjustment': shelter,
        'breaking_wave_min': breaking_min, 'breaking_wave_max': breaking_max,
        'hazard_flags_json': bounded_json(hazards, max_items=32, max_bytes=16_384),
        'uncertainty_factors_json': bounded_json({'factors': uncertainty}, max_items=64, max_bytes=32_768),
        'factor_details_json': details,
    }


def in_circular_range(angle, start, end):
    values = (_finite(angle), _finite(start), _finite(end))
    if any(value is None for value in values):
        return False
    angle, start, end = (value % 360 for value in values)
    return start <= angle <= end if start <= end else angle >= start or angle <= end


def circular_direction_fit(angle, pref_min, pref_max, acc_min, acc_max, config):
    angle = _direction(angle)
    if angle is None or _direction(pref_min) is None or _direction(pref_max) is None:
        return None
    if in_circular_range(angle, pref_min, pref_max):
        return 100.0
    if _direction(acc_min) is None or _direction(acc_max) is None:
        return config.outside_direction_fit
    if in_circular_range(angle, acc_min, acc_max):
        distance = min(_angular_distance(angle, pref_min), _angular_distance(angle, pref_max))
        # Tapers from acceptable_direction_fit at a preferred boundary to 25% of
        # that partial fit at the farthest possible circular distance.
        return _score(config.acceptable_direction_fit * max(0.25, 1.0 - distance / 180.0))
    return config.outside_direction_fit


def preferred_direction_fit(angle, lo, hi):
    if _direction(angle) is None or _direction(lo) is None or _direction(hi) is None:
        return None
    return 100.0 if in_circular_range(angle, lo, hi) else 0.0


def range_fit(value, lo, hi, *, taper_fraction=1.0):
    value, lo, hi = _finite(value), _finite(lo), _finite(hi)
    if value is None or lo is None or hi is None or lo > hi:
        return None
    if lo <= value <= hi:
        return 100.0
    width = max(hi - lo, 1.0) * taper_fraction
    distance = lo - value if value < lo else value - hi
    return _score(100.0 * (1.0 - distance / width))


def wind_speed_fit_global(value, config):
    value = _finite(value)
    if value is None or value < 0:
        return None
    if value <= config.global_wind_safe_speed:
        return 100.0
    return _score(100 * (config.global_wind_zero_fit_speed - value) / (config.global_wind_zero_fit_speed - config.global_wind_safe_speed))


def provisional_breaking_range(height, direction_fit, period, exposure, shelter, tide_fit, config):
    height = _finite(height)
    if height is None or height < 0:
        return None, None, {'method': 'model-derived provisional', 'available': False, 'reason': 'missing_valid_height'}
    direction_multiplier = 0.65 if direction_fit is None else 0.65 + 0.35 * direction_fit / 100
    period_value = config.period_energy_base_seconds if _finite(period) is None else min(config.period_energy_cap_seconds, max(config.period_energy_base_seconds, period))
    period_multiplier = 1 + (period_value - config.period_energy_base_seconds) * config.period_energy_per_second
    tide_multiplier = 0.95 if tide_fit is None else 0.9 + 0.1 * tide_fit / 100
    face = max(0.0, height * direction_multiplier * period_multiplier * exposure * shelter * tide_multiplier)
    lower = _practical_round(face * config.breaking_lower_multiplier, config.breaking_rounding_metres)
    upper = _practical_round(face * config.breaking_upper_multiplier, config.breaking_rounding_metres)
    upper = max(lower, upper)
    return lower, upper, {'method': 'model-derived provisional', 'observed': False, 'live': False, 'formula_version': FORMULA_VERSION, 'multipliers': {'direction': _round(direction_multiplier), 'period': _round(period_multiplier), 'exposure': exposure, 'shelter': shelter, 'tide': _round(tide_multiplier)}, 'unrounded_face_m': _round(face, 3), 'rounding_increment_m': config.breaking_rounding_metres}


def calculate_spot_assessment(db: Session, consensus_run_id: int, *, spot_ids=None, force=False, dry_run=False):
    config = default_spot_intelligence_configuration()
    request = SpotAssessmentRequest(consensus_run_id, tuple(spot_ids) if spot_ids else None, config.engine_version, config, force, dry_run)
    return SpotIntelligenceEngine(db).calculate(request)


def _validated_request(request):
    request.configuration.validate()
    if isinstance(request.consensus_run_id, bool) or not isinstance(request.consensus_run_id, int) or request.consensus_run_id <= 0:
        raise ValueError('consensus_run_id must be a positive integer')
    if request.engine_version != request.configuration.engine_version:
        raise ValueError('request engine_version must match configuration engine_version')
    spot_ids = tuple(sorted(set(request.spot_ids))) if request.spot_ids else None
    if spot_ids and any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in spot_ids):
        raise ValueError('spot_ids must be positive integers')
    return SpotAssessmentRequest(request.consensus_run_id, spot_ids, request.engine_version, request.configuration, request.force_recalculation, request.dry_run)


def _primary(primary, fallback):
    primary = _finite(primary)
    if primary is not None and primary >= 0:
        return primary, 'primary_swell'
    fallback = _finite(fallback)
    if fallback is not None and fallback >= 0:
        return fallback, 'total_wave_fallback'
    return None, 'missing'


def _bounded_factor(value, lo, hi):
    value = _finite(value)
    if value is None or value <= 0:
        return 1.0, True
    return max(lo, min(hi, value)), value < lo or value > hi


def _direction(value):
    value = _finite(value)
    return value if value is not None and 0 <= value < 360 else None


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    return float(value)


def _angular_distance(a, b):
    return abs((a - b + 180) % 360 - 180)


def _score(value):
    return round(max(0.0, min(100.0, float(value))), 3)


def _round(value, digits=3):
    return round(float(value), digits)


def _practical_round(value, increment):
    rounded = round(max(0.0, value) / increment) * increment
    # Honour configurable increments such as 0.25 instead of silently forcing
    # every result to one decimal place. Validation guarantees a finite,
    # positive increment; Decimal is used only to derive display precision.
    precision = max(0, -int(Decimal(str(increment)).normalize().as_tuple().exponent))
    return round(rounded, min(precision, 12))


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def _safe_error(exc):
    return redact_text(f'{type(exc).__name__}: {exc}', max_length=1000)
