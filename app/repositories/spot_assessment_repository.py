from __future__ import annotations

from typing import Iterable

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..forecast_ledger_models import SpotAssessmentPoint, SpotAssessmentRun
from ..services.consensus_safety import redact_text
from .ledger_utils import utc_now


class SpotAssessmentRunTransitionError(RuntimeError):
    pass


def create_spot_assessment_run(db: Session, **values) -> SpotAssessmentRun:
    if values.get('status', 'running') != 'running':
        raise SpotAssessmentRunTransitionError('spot assessment runs must be created in running state')
    values['status'] = 'running'
    values.setdefault('created_at', utc_now())
    row = SpotAssessmentRun(**values)
    db.add(row)
    db.flush()
    return row


def get_spot_assessment_run(db: Session, run_id: int) -> SpotAssessmentRun | None:
    return db.get(SpotAssessmentRun, run_id)


def mark_spot_assessment_run_status(db: Session, run_id: int, status: str, *, error_message: str | None = None, metadata_json: dict | None = None) -> SpotAssessmentRun:
    if status not in {'completed', 'failed'}:
        raise SpotAssessmentRunTransitionError('only running -> completed|failed transitions are allowed')
    values: dict = {'status': status}
    if error_message is not None:
        # Repository callers must not be able to bypass the persisted audit
        # redaction performed by the engine/CLI boundary.
        values['error_message'] = redact_text(error_message, max_length=1000)
    if metadata_json is not None:
        values['metadata_json'] = metadata_json
    result = db.execute(update(SpotAssessmentRun).where(SpotAssessmentRun.id == run_id, SpotAssessmentRun.status == 'running').values(**values))
    if result.rowcount != 1:
        raise SpotAssessmentRunTransitionError(f'assessment run {run_id} does not exist in running state')
    db.flush()
    row = db.get(SpotAssessmentRun, run_id)
    if row is None:
        raise SpotAssessmentRunTransitionError(f'assessment run {run_id} disappeared during transition')
    db.refresh(row)
    return row


def create_spot_assessment_points(db: Session, points: Iterable[dict | SpotAssessmentPoint]) -> list[SpotAssessmentPoint]:
    values = list(points)
    if not values:
        return []
    run_ids = {int(item.assessment_run_id if isinstance(item, SpotAssessmentPoint) else item['assessment_run_id']) for item in values}
    if len(run_ids) != 1:
        raise SpotAssessmentRunTransitionError('point batches must target exactly one assessment run')
    run = db.get(SpotAssessmentRun, next(iter(run_ids)))
    if run is None or run.status != 'running':
        raise SpotAssessmentRunTransitionError('assessment points may only be inserted into an existing running run')
    rows = []
    for item in values:
        if isinstance(item, SpotAssessmentPoint):
            row = item
        else:
            item = dict(item)
            item.setdefault('created_at', utc_now())
            row = SpotAssessmentPoint(**item)
        rows.append(row)
    db.add_all(rows)
    db.flush()
    return rows


def find_equivalent_completed_assessment(db: Session, *, consensus_run_id: int, rules_hash: str, engine_version: str, configuration_hash: str, scope_hash: str) -> SpotAssessmentRun | None:
    stmt = select(SpotAssessmentRun).where(
        SpotAssessmentRun.status == 'completed',
        SpotAssessmentRun.consensus_run_id == consensus_run_id,
        SpotAssessmentRun.spot_rules_hash == rules_hash,
        SpotAssessmentRun.spot_intelligence_engine_version == engine_version,
        SpotAssessmentRun.configuration_hash == configuration_hash,
        SpotAssessmentRun.calculation_scope_hash == scope_hash,
    ).order_by(SpotAssessmentRun.calculated_at.desc(), SpotAssessmentRun.id.desc()).limit(1)
    return db.scalar(stmt)


def find_latest_equivalent_assessment(db: Session, *, consensus_run_id: int, rules_hash: str, engine_version: str, configuration_hash: str, scope_hash: str) -> SpotAssessmentRun | None:
    stmt = select(SpotAssessmentRun).where(
        SpotAssessmentRun.consensus_run_id == consensus_run_id,
        SpotAssessmentRun.spot_rules_hash == rules_hash,
        SpotAssessmentRun.spot_intelligence_engine_version == engine_version,
        SpotAssessmentRun.configuration_hash == configuration_hash,
        SpotAssessmentRun.calculation_scope_hash == scope_hash,
    ).order_by(SpotAssessmentRun.recalculation_sequence.desc(), SpotAssessmentRun.id.desc()).limit(1)
    return db.scalar(stmt)


def next_spot_assessment_recalculation_sequence(db: Session, *, consensus_run_id: int, rules_hash: str, engine_version: str, configuration_hash: str, scope_hash: str) -> int:
    """Return the next append-only attempt sequence for equivalent inputs."""
    value = db.scalar(select(func.max(SpotAssessmentRun.recalculation_sequence)).where(
        SpotAssessmentRun.consensus_run_id == consensus_run_id,
        SpotAssessmentRun.spot_rules_hash == rules_hash,
        SpotAssessmentRun.spot_intelligence_engine_version == engine_version,
        SpotAssessmentRun.configuration_hash == configuration_hash,
        SpotAssessmentRun.calculation_scope_hash == scope_hash,
    ))
    return int(value or 0) + 1


def list_spot_assessment_points_for_run(db: Session, run_id: int, *, limit: int | None = None, offset: int = 0) -> list[SpotAssessmentPoint]:
    stmt = select(SpotAssessmentPoint).where(SpotAssessmentPoint.assessment_run_id == run_id).order_by(SpotAssessmentPoint.valid_at, SpotAssessmentPoint.spot_id, SpotAssessmentPoint.id)
    if limit is not None:
        stmt = stmt.limit(limit)
    if offset:
        stmt = stmt.offset(offset)
    return list(db.scalars(stmt))


def count_spot_assessment_points_for_run(db: Session, run_id: int) -> int:
    return int(db.scalar(select(func.count()).select_from(SpotAssessmentPoint).where(SpotAssessmentPoint.assessment_run_id == run_id)) or 0)


def get_spot_assessment_point(db: Session, point_id: int) -> SpotAssessmentPoint | None:
    return db.get(SpotAssessmentPoint, point_id)


def count_spot_assessment_runs(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(SpotAssessmentRun)) or 0)


def latest_spot_assessment_runs(db: Session, *, limit: int = 20, offset: int = 0) -> list[SpotAssessmentRun]:
    return list(db.scalars(select(SpotAssessmentRun).order_by(SpotAssessmentRun.calculated_at.desc(), SpotAssessmentRun.id.desc()).limit(limit).offset(offset)))
