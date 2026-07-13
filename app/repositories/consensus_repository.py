from __future__ import annotations

from datetime import datetime
from typing import Iterable

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..forecast_ledger_models import ConsensusForecastPoint, ConsensusRun
from .ledger_utils import utc_now


class ConsensusRunTransitionError(RuntimeError):
    pass


def create_consensus_run(db: Session, **values) -> ConsensusRun:
    if values.get('status', 'running') != 'running':
        raise ConsensusRunTransitionError('consensus runs must be created in running state')
    values['status'] = 'running'
    values.setdefault('created_at', utc_now())
    run = ConsensusRun(**values)
    db.add(run)
    db.flush()
    return run


def get_consensus_run(db: Session, run_id: int) -> ConsensusRun | None:
    return db.get(ConsensusRun, run_id)


def mark_consensus_run_status(db: Session, run_id: int, status: str, *, error_message: str | None = None, metadata_json: dict | None = None) -> ConsensusRun:
    if status not in {'completed', 'failed'}:
        raise ConsensusRunTransitionError('only running -> completed|failed transitions are allowed')
    values: dict = {'status': status}
    if error_message is not None:
        values['error_message'] = error_message[:1000]
    if metadata_json is not None:
        values['metadata_json'] = metadata_json
    result = db.execute(update(ConsensusRun).where(ConsensusRun.id == run_id, ConsensusRun.status == 'running').values(**values))
    if result.rowcount != 1:
        raise ConsensusRunTransitionError(f'run {run_id} does not exist in running state')
    db.flush()
    run = db.get(ConsensusRun, run_id)
    if run is None:
        raise ConsensusRunTransitionError(f'run {run_id} disappeared during transition')
    db.refresh(run)
    return run


def find_equivalent_completed_run(db: Session, *, engine_version: str, configuration_hash: str, input_fingerprint: str) -> ConsensusRun | None:
    stmt = select(ConsensusRun).where(ConsensusRun.status == 'completed', ConsensusRun.consensus_engine_version == engine_version, ConsensusRun.configuration_hash == configuration_hash, ConsensusRun.metadata_json['input_fingerprint'].as_string() == input_fingerprint).order_by(ConsensusRun.calculated_at.desc(), ConsensusRun.id.desc()).limit(1)
    return db.scalar(stmt)


def insert_consensus_points(db: Session, rows: Iterable[dict]) -> list[ConsensusForecastPoint]:
    rows = list(rows)
    if not rows:
        return []
    run_ids = {int(row['consensus_run_id']) for row in rows}
    if len(run_ids) != 1:
        raise ConsensusRunTransitionError('point batches must target exactly one consensus run')
    run = db.get(ConsensusRun, next(iter(run_ids)))
    if run is None or run.status != 'running':
        raise ConsensusRunTransitionError('consensus points may only be inserted into an existing running run')
    points = []
    for row in rows:
        row = dict(row)
        row.setdefault('created_at', utc_now())
        points.append(ConsensusForecastPoint(**row))
    db.add_all(points)
    db.flush()
    return points


def list_consensus_points_for_run(db: Session, consensus_run_id: int, *, limit: int | None = None) -> list[ConsensusForecastPoint]:
    stmt = select(ConsensusForecastPoint).where(ConsensusForecastPoint.consensus_run_id == consensus_run_id).order_by(ConsensusForecastPoint.valid_at, ConsensusForecastPoint.spot_id, ConsensusForecastPoint.id)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(db.scalars(stmt))


def count_consensus_points_for_run(db: Session, consensus_run_id: int) -> int:
    return int(db.scalar(select(func.count()).select_from(ConsensusForecastPoint).where(ConsensusForecastPoint.consensus_run_id == consensus_run_id)) or 0)


def get_consensus_point(db: Session, point_id: int) -> ConsensusForecastPoint | None:
    return db.get(ConsensusForecastPoint, point_id)


def latest_consensus_runs(db: Session, *, limit: int = 20) -> list[ConsensusRun]:
    return list(db.scalars(select(ConsensusRun).order_by(ConsensusRun.calculated_at.desc(), ConsensusRun.id.desc()).limit(limit)))


# Compatibility helper for schema/bootstrap callers.
def create_consensus_points(db: Session, rows: Iterable[dict]) -> list[ConsensusForecastPoint]:
    return insert_consensus_points(db, rows)
