from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from ..repositories.consensus_repository import create_consensus_run, find_equivalent_completed_run, insert_consensus_points, list_consensus_points_for_run, mark_consensus_run_status
from .consensus_configuration import CONSENSUS_FIELDS, ConsensusConfiguration, default_consensus_configuration
from .consensus_input_selector import SelectedProviderInput, SelectionResult, select_consensus_inputs
from .consensus_safety import bounded_json, compact_provenance, redact_text
from .consensus_statistics import WeightedValue, direction_consensus, scalar_consensus, to_utc


@dataclass(frozen=True)
class ConsensusCalculationRequest:
    forecast_cutoff_at: datetime
    valid_from: datetime
    valid_until: datetime
    spot_ids: tuple[int, ...] | None
    engine_version: str
    configuration: ConsensusConfiguration
    trigger_reason: str
    correlation_id: str | None = None
    force_recalculation: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class ConsensusCalculationResult:
    consensus_run_id: int | None
    points_written: int
    spots_processed: int
    valid_times_processed: int
    provider_names: tuple[str, ...]
    status: str
    warnings: tuple[str, ...]
    input_fingerprint: str
    duration_seconds: float


class ConsensusEngine:
    def __init__(self, db: Session):
        self.db = db

    def calculate(self, request: ConsensusCalculationRequest) -> ConsensusCalculationResult:
        started = perf_counter()
        request = _validated_request(request)
        configuration_hash = request.configuration.configuration_hash()
        stage = 'select_inputs'
        try:
            selection = select_consensus_inputs(
                self.db,
                cutoff=request.forecast_cutoff_at,
                valid_from=request.valid_from,
                valid_until=request.valid_until,
                spot_ids=request.spot_ids,
                configuration=request.configuration,
            )
            stage = 'input_fingerprint'
            fingerprint = _input_fingerprint(request, selection, configuration_hash)
        except Exception as exc:
            self.db.rollback()
            if not request.dry_run:
                self._persist_precalculation_failure(request, configuration_hash, stage, exc, started)
            raise
        # Dry runs are fresh previews and never consult persisted equivalents.
        if not request.dry_run and not request.force_recalculation:
            existing = find_equivalent_completed_run(self.db, engine_version=request.engine_version, configuration_hash=configuration_hash, input_fingerprint=fingerprint)
            if existing:
                points = list_consensus_points_for_run(self.db, existing.id)
                return ConsensusCalculationResult(existing.id, 0, len({p.spot_id for p in points}), len({to_utc(p.valid_at) for p in points}), selection.provider_names, 'reused', selection.warnings, fingerprint, perf_counter() - started)
        keys = set(selection.inputs_by_spot_time_field) | set(selection.excluded_by_spot_time_field)
        spots = len({key[0] for key in keys})
        valid_times = len({key[1] for key in keys})
        if request.dry_run:
            rows = self._build_points(None, selection, request.configuration)
            return ConsensusCalculationResult(None, len(rows), spots, valid_times, selection.provider_names, 'dry_run', selection.warnings, fingerprint, perf_counter() - started)
        run = create_consensus_run(
            self.db,
            calculated_at=datetime.now(UTC),
            forecast_cutoff_at=to_utc(request.forecast_cutoff_at),
            consensus_engine_version=request.engine_version,
            configuration_hash=configuration_hash,
            status='running',
            metadata_json=bounded_json({
                'input_fingerprint': fingerprint,
                'trigger_reason': redact_text(request.trigger_reason, max_length=80),
                'correlation_id': redact_text(request.correlation_id, max_length=128) if request.correlation_id else None,
                'valid_from': to_utc(request.valid_from).isoformat(),
                'valid_until': to_utc(request.valid_until).isoformat(),
                'spot_ids': list(request.spot_ids) if request.spot_ids else None,
                'providers_selected': list(selection.provider_names),
                'configuration_hash': configuration_hash,
                'point_set_count': selection.point_count,
                'warnings': list(selection.warnings),
            }, max_bytes=16_384),
        )
        self.db.commit()
        run_id = run.id
        stage = 'build_points'
        try:
            rows = self._build_points(run_id, selection, request.configuration)
            stage = 'insert_points'
            insert_consensus_points(self.db, rows)
            stage = 'complete_run'
            metadata = dict(run.metadata_json or {})
            metadata.update({'duration_seconds': perf_counter() - started, 'points_written': len(rows), 'status': 'completed'})
            mark_consensus_run_status(self.db, run_id, 'completed', metadata_json=bounded_json(metadata, max_bytes=16_384))
            self.db.commit()
            return ConsensusCalculationResult(run_id, len(rows), spots, valid_times, selection.provider_names, 'completed', selection.warnings, fingerprint, perf_counter() - started)
        except Exception as exc:
            self.db.rollback()
            failed_metadata = dict(run.metadata_json or {})
            failed_metadata.update({'status': 'failed', 'failure_stage': redact_text(stage, max_length=40), 'duration_seconds': perf_counter() - started})
            try:
                mark_consensus_run_status(self.db, run_id, 'failed', error_message=_safe_error(exc), metadata_json=bounded_json(failed_metadata, max_bytes=16_384))
                self.db.commit()
            except Exception:
                self.db.rollback()
            raise

    def _persist_precalculation_failure(self, request: ConsensusCalculationRequest, configuration_hash: str, stage: str, exc: Exception, started: float) -> None:
        error = _safe_error(exc)
        metadata = bounded_json({
            'status': 'failed',
            'failure_stage': stage,
            'error': error,
            'duration_seconds': perf_counter() - started,
            'request_scope': {
                'forecast_cutoff_at': to_utc(request.forecast_cutoff_at).isoformat(),
                'valid_from': to_utc(request.valid_from).isoformat(),
                'valid_until': to_utc(request.valid_until).isoformat(),
                'spot_ids': list(request.spot_ids) if request.spot_ids else None,
            },
            'trigger_reason': redact_text(request.trigger_reason, max_length=80),
            'correlation_id': redact_text(request.correlation_id, max_length=128) if request.correlation_id else None,
            'engine_version': request.engine_version,
            'configuration_hash': configuration_hash,
        }, max_bytes=16_384)
        try:
            run = create_consensus_run(
                self.db,
                calculated_at=datetime.now(UTC),
                forecast_cutoff_at=to_utc(request.forecast_cutoff_at),
                consensus_engine_version=request.engine_version,
                configuration_hash=configuration_hash,
                status='running',
                metadata_json=metadata,
            )
            mark_consensus_run_status(self.db, run.id, 'failed', error_message=error, metadata_json=metadata)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def _build_points(self, run_id: int | None, selection: SelectionResult, configuration: ConsensusConfiguration) -> list[dict[str, Any]]:
        keys = set(selection.inputs_by_spot_time_field) | set(selection.excluded_by_spot_time_field)
        spot_times = sorted({(spot_id, valid_at) for spot_id, valid_at, _ in keys})
        rows: list[dict[str, Any]] = []
        expected = set(configuration.expected_fields)
        direction_fields = set(configuration.direction_fields)
        for spot_id, valid_at in spot_times:
            row: dict[str, Any] = {'consensus_run_id': run_id or 0, 'spot_id': spot_id, 'valid_at': valid_at}
            field_details: dict[str, Any] = {}
            field_scores: list[float] = []
            freshness_scores: list[float] = []
            spatial_scores: list[float] = []
            providers: set[str] = set()
            populated_expected = 0
            for field in CONSENSUS_FIELDS:
                key = (spot_id, valid_at, field)
                inputs = selection.inputs_by_spot_time_field.get(key, [])
                selector_excluded = selection.excluded_by_spot_time_field.get(key, [])
                values = [WeightedValue(item.provider_name, item.value, item.effective_weight, item.provenance) for item in inputs]
                result = direction_consensus(field, values, configuration) if field in direction_fields else scalar_consensus(field, values, configuration)
                row[field] = result.value
                if result.value is not None and field in expected:
                    populated_expected += 1
                combined_excluded = list(selector_excluded) + list(result.excluded)
                field_details[field] = {
                    'value': result.value,
                    'agreement_score': _score(result.agreement_score),
                    'freshness_score': _score(result.freshness_score),
                    'spatial_relevance_score': _score(result.spatial_relevance_score),
                    'contributors': [compact_provenance(item) for item in result.contributors],
                    'excluded': [compact_provenance(item) for item in combined_excluded],
                    'contributor_count': len(result.contributors),
                    'excluded_count': len(combined_excluded),
                    'warning': result.warning,
                    'minimum_providers': configuration.minimum_providers_per_field.get(field, 1),
                }
                if result.value is not None:
                    active_providers = {item['provider_name'] for item in result.contributors if item.get('provider_name') and not item.get('excluded')}
                    providers.update(active_providers)
                    field_scores.append(result.agreement_score)
                    freshness_scores.append(result.freshness_score)
                    spatial_scores.append(result.spatial_relevance_score)
            completeness = _score((populated_expected / len(expected)) * 100.0)
            agreement = _score(sum(field_scores) / len(field_scores) if field_scores else 0.0)
            freshness = _score(sum(freshness_scores) / len(freshness_scores) if freshness_scores else 0.0)
            spatial = _score(sum(spatial_scores) / len(spatial_scores) if spatial_scores else 0.0)
            weights = configuration.confidence_input_weights
            confidence_input = _score(agreement * weights.agreement + freshness * weights.freshness + completeness * weights.completeness + spatial * weights.spatial_relevance)
            row.update({
                'provider_count': len(providers),
                'provider_ids_json': sorted(providers),
                'agreement_score': agreement,
                'freshness_score': freshness,
                'completeness_score': completeness,
                'confidence_input_score': confidence_input,
                'calculation_details_json': bounded_json({
                    'engine_version': configuration.engine_version,
                    'configuration_hash': configuration.configuration_hash(),
                    'fields': field_details,
                    'confidence_input_only': True,
                    'not_final_confidence': True,
                    'spot_intelligence_applied': False,
                    'recommendation_logic_applied': False,
                    'time_alignment': 'exact_valid_at_only',
                    'spatial_relevance_score': spatial,
                }, max_items=64),
            })
            rows.append(row)
        return rows


def calculate_latest(db: Session, *, hours: int = 72, spot_ids: tuple[int, ...] | None = None, force: bool = False, dry_run: bool = False, trigger_reason: str = 'manual_cli') -> ConsensusCalculationResult:
    if hours < 0:
        raise ValueError('hours must be non-negative')
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    configuration = default_consensus_configuration()
    return ConsensusEngine(db).calculate(ConsensusCalculationRequest(now, now, now + __import__('datetime').timedelta(hours=hours), spot_ids, configuration.engine_version, configuration, trigger_reason, force_recalculation=force, dry_run=dry_run))


def _validated_request(request: ConsensusCalculationRequest) -> ConsensusCalculationRequest:
    request.configuration.validate()
    if request.engine_version != request.configuration.engine_version:
        raise ValueError('request engine_version must match configuration engine_version')
    cutoff, valid_from, valid_until = map(to_utc, (request.forecast_cutoff_at, request.valid_from, request.valid_until))
    if valid_from > valid_until:
        raise ValueError('valid_from must not be after valid_until')
    if not isinstance(request.trigger_reason, str) or not request.trigger_reason.strip() or len(request.trigger_reason) > 80:
        raise ValueError('trigger_reason must be 1..80 characters')
    if request.correlation_id is not None and (not isinstance(request.correlation_id, str) or len(request.correlation_id) > 128):
        raise ValueError('correlation_id must be at most 128 characters')
    spot_ids = tuple(sorted(set(request.spot_ids))) if request.spot_ids else None
    if spot_ids and any(isinstance(value, bool) or value <= 0 for value in spot_ids):
        raise ValueError('spot_ids must be positive integers')
    return ConsensusCalculationRequest(cutoff, valid_from, valid_until, spot_ids, request.engine_version, request.configuration, request.trigger_reason.strip(), request.correlation_id, request.force_recalculation, request.dry_run)


def _score(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def _safe_error(exc: Exception) -> str:
    return redact_text(f'{type(exc).__name__}: {exc}', max_length=1000)


def _input_fingerprint(request: ConsensusCalculationRequest, selection: SelectionResult, configuration_hash: str) -> str:
    point_ids = {
        int(item.provenance['forecast_point_id'])
        for values in selection.inputs_by_spot_time_field.values()
        for item in values
    }
    point_ids.update(
        int(item['forecast_point_id'])
        for values in selection.excluded_by_spot_time_field.values()
        for item in values
        if item.get('forecast_point_id') is not None
    )
    payload = {
        'cutoff': to_utc(request.forecast_cutoff_at).isoformat(),
        'valid_from': to_utc(request.valid_from).isoformat(),
        'valid_until': to_utc(request.valid_until).isoformat(),
        'spot_ids': list(request.spot_ids) if request.spot_ids else None,
        'engine_version': request.engine_version,
        'configuration_hash': configuration_hash,
        'provider_point_ids': sorted(point_ids),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
