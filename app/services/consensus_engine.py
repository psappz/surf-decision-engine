from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from ..repositories.consensus_repository import create_consensus_run, find_equivalent_completed_run, insert_consensus_points, mark_consensus_run_status, list_consensus_points_for_run
from .consensus_configuration import CONSENSUS_FIELDS, DIRECTION_FIELDS, ConsensusConfiguration, default_consensus_configuration
from .consensus_input_selector import SelectedProviderInput, select_consensus_inputs
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
    providers_used: tuple[str, ...]
    status: str
    warnings: tuple[str, ...]
    input_fingerprint: str | None = None
    duration_seconds: float | None = None


class ConsensusEngine:
    def __init__(self, db: Session):
        self.db = db

    def calculate(self, request: ConsensusCalculationRequest) -> ConsensusCalculationResult:
        started = perf_counter()
        cfg_hash = request.configuration.configuration_hash()
        selection = select_consensus_inputs(
            self.db,
            forecast_cutoff_at=request.forecast_cutoff_at,
            valid_from=request.valid_from,
            valid_until=request.valid_until,
            spot_ids=request.spot_ids,
            configuration=request.configuration,
        )
        fingerprint = _input_fingerprint(request, cfg_hash, selection.inputs_by_spot_time_field)
        if not request.force_recalculation:
            existing = find_equivalent_completed_run(self.db, engine_version=request.engine_version, configuration_hash=cfg_hash, input_fingerprint=fingerprint)
            if existing:
                points = list_consensus_points_for_run(self.db, existing.id)
                return ConsensusCalculationResult(existing.id, 0, len({p.spot_id for p in points}), len({to_utc(p.valid_at) for p in points}), selection.provider_names, 'reused', selection.warnings, fingerprint, perf_counter() - started)
        rows = self._build_points(None, selection.inputs_by_spot_time_field, request.configuration)
        spots = len({row['spot_id'] for row in rows})
        valid_times = len({to_utc(row['valid_at']) for row in rows})
        if request.dry_run:
            return ConsensusCalculationResult(None, len(rows), spots, valid_times, selection.provider_names, 'dry_run', selection.warnings, fingerprint, perf_counter() - started)
        run = None
        try:
            run = create_consensus_run(
                self.db,
                calculated_at=datetime.now(UTC),
                forecast_cutoff_at=to_utc(request.forecast_cutoff_at),
                consensus_engine_version=request.engine_version,
                configuration_hash=cfg_hash,
                status='running',
                metadata_json={
                    'input_fingerprint': fingerprint,
                    'trigger_reason': request.trigger_reason,
                    'correlation_id': request.correlation_id,
                    'valid_from': to_utc(request.valid_from).isoformat(),
                    'valid_until': to_utc(request.valid_until).isoformat(),
                    'spot_ids': list(request.spot_ids) if request.spot_ids else None,
                    'providers_selected': list(selection.provider_names),
                    'configuration_hash': cfg_hash,
                    'point_set_count': selection.point_count,
                    'warnings': list(selection.warnings),
                },
            )
            # Persist the run before point calculation so a later rollback can
            # leave an auditable failed run without committing partial points.
            self.db.commit()
            rows = self._build_points(run.id, selection.inputs_by_spot_time_field, request.configuration)
            insert_consensus_points(self.db, rows)
            metadata = dict(run.metadata_json or {})
            metadata.update({'duration_seconds': perf_counter() - started, 'points_written': len(rows), 'status': 'completed'})
            mark_consensus_run_status(self.db, run.id, 'completed', metadata_json=metadata)
            self.db.commit()
            return ConsensusCalculationResult(run.id, len(rows), spots, valid_times, selection.provider_names, 'completed', selection.warnings, fingerprint, perf_counter() - started)
        except Exception as exc:
            self.db.rollback()
            if run and getattr(run, 'id', None):
                try:
                    mark_consensus_run_status(self.db, run.id, 'failed', error_message=_safe_error(exc))
                    self.db.commit()
                except Exception:
                    self.db.rollback()
            raise

    def _build_points(self, run_id: int | None, grouped: dict[tuple[int, datetime, str], list[SelectedProviderInput]], cfg: ConsensusConfiguration) -> list[dict[str, Any]]:
        by_spot_time: dict[tuple[int, datetime], dict[str, list[SelectedProviderInput]]] = {}
        for (spot_id, valid_at, field), inputs in grouped.items():
            by_spot_time.setdefault((spot_id, valid_at), {})[field] = inputs
        rows: list[dict[str, Any]] = []
        for (spot_id, valid_at), fields in sorted(by_spot_time.items(), key=lambda item: (item[0][0], item[0][1])):
            row: dict[str, Any] = {'consensus_run_id': run_id or 0, 'spot_id': spot_id, 'valid_at': valid_at}
            field_details: dict[str, Any] = {}
            field_scores = []
            freshness_scores = []
            spatial_scores = []
            providers = set()
            available_expected = 0
            for field in CONSENSUS_FIELDS:
                inputs = fields.get(field, [])
                values = [WeightedValue(i.provider_name, i.value, i.effective_weight, i.provenance) for i in inputs]
                result = direction_consensus(field, values, cfg) if field in DIRECTION_FIELDS else scalar_consensus(field, values, cfg)
                if result.value is not None:
                    row[field] = result.value
                    available_expected += 1
                elif field in _model_point_fields():
                    row[field] = None
                field_details[field] = {
                    'value': result.value,
                    'agreement_score': result.agreement_score,
                    'freshness_score': result.freshness_score,
                    'spatial_relevance_score': result.spatial_relevance_score,
                    'contributors': _bounded_provenance(result.contributors),
                    'excluded': _bounded_provenance(result.excluded),
                    'contributor_count': len(result.contributors),
                    'excluded_count': len(result.excluded),
                    'warning': result.warning,
                    'minimum_providers': cfg.minimum_providers_per_field.get(field, 1),
                }
                if inputs:
                    providers.update(i.provider_name for i in inputs)
                    field_scores.append(result.agreement_score)
                    freshness_scores.append(result.freshness_score)
                    spatial_scores.append(result.spatial_relevance_score)
            completeness = (available_expected / len(cfg.expected_fields)) * 100.0 if cfg.expected_fields else 0.0
            agreement = sum(field_scores) / len(field_scores) if field_scores else 0.0
            freshness = sum(freshness_scores) / len(freshness_scores) if freshness_scores else 0.0
            spatial = sum(spatial_scores) / len(spatial_scores) if spatial_scores else 0.0
            w = cfg.confidence_input_weights
            confidence_input = agreement * w.agreement + freshness * w.freshness + completeness * w.completeness + spatial * w.spatial_relevance
            row.update({
                'provider_count': len(providers),
                'provider_ids_json': sorted(providers),
                'agreement_score': agreement,
                'freshness_score': freshness,
                'completeness_score': completeness,
                'confidence_input_score': confidence_input,
                'calculation_details_json': {
                    'engine_version': cfg.engine_version,
                    'configuration_hash': cfg.configuration_hash(),
                    'fields': field_details,
                    'confidence_input_score_is_final_confidence': False,
                    'time_alignment': 'exact_valid_at_only',
                    'interpolation': 'none',
                    'spot_intelligence_applied': False,
                    'recommendation_logic_applied': False,
                },
            })
            rows.append(row)
        return rows


def _model_point_fields() -> set[str]:
    return set(CONSENSUS_FIELDS)


def _bounded_provenance(items: tuple[dict[str, Any], ...], limit: int = 12) -> list[dict[str, Any]]:
    """Keep provenance structured but bounded; counts preserve truncation context."""
    ordered = sorted(items, key=lambda p: (str(p.get('provider_name')), int(p.get('forecast_point_id') or 0)))
    out = [dict(item) for item in ordered[:limit]]
    if len(ordered) > limit:
        out.append({'truncated': True, 'omitted_count': len(ordered) - limit})
    return out


def _safe_error(exc: Exception) -> str:
    text = f'{type(exc).__name__}: {exc}'
    return text[:1000]


def _input_fingerprint(request: ConsensusCalculationRequest, cfg_hash: str, grouped: dict[tuple[int, datetime, str], list[SelectedProviderInput]]) -> str:
    point_ids = sorted({i.point.id for inputs in grouped.values() for i in inputs})
    payload = {
        'forecast_cutoff_at': to_utc(request.forecast_cutoff_at).isoformat(),
        'valid_from': to_utc(request.valid_from).isoformat(),
        'valid_until': to_utc(request.valid_until).isoformat(),
        'spot_ids': list(request.spot_ids) if request.spot_ids else None,
        'engine_version': request.engine_version,
        'configuration_hash': cfg_hash,
        'provider_point_ids': point_ids,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def calculate_latest(db: Session, *, hours: int = 72, spot_ids: tuple[int, ...] | None = None, force: bool = False) -> ConsensusCalculationResult:
    now = datetime.now(UTC)
    cfg = default_consensus_configuration()
    return ConsensusEngine(db).calculate(ConsensusCalculationRequest(forecast_cutoff_at=now, valid_from=now, valid_until=now.replace(microsecond=0) if hours == 0 else now + __import__('datetime').timedelta(hours=hours), spot_ids=spot_ids, engine_version=cfg.engine_version, configuration=cfg, trigger_reason='manual_latest', force_recalculation=force))
