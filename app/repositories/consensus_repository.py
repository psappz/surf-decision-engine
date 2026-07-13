from __future__ import annotations

from datetime import datetime
from typing import Iterable

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..forecast_ledger_models import ConsensusForecastPoint, ConsensusRun
from .ledger_utils import utc_now


def create_consensus_run(db: Session, **values) -> ConsensusRun:
    row = ConsensusRun(created_at=values.pop('created_at', utc_now()), **values)
    db.add(row)
    db.flush()
    return row


def mark_consensus_run_status(db: Session, consensus_run_id: int, status: str, *, error_message: str | None = None, metadata_json: dict | None = None) -> ConsensusRun | None:
    run = db.get(ConsensusRun, consensus_run_id)
    if not run:
        return None
    run.status = status
    if error_message is not None:
        run.error_message = error_message[:2000]
    if metadata_json is not None:
        run.metadata_json = metadata_json
    db.flush()
    return run


def find_equivalent_completed_run(db: Session, *, engine_version: str, configuration_hash: str, input_fingerprint: str) -> ConsensusRun | None:
    stmt = select(ConsensusRun).where(
        ConsensusRun.consensus_engine_version == engine_version,
        ConsensusRun.configuration_hash == configuration_hash,
        ConsensusRun.status == 'completed',
    ).order_by(ConsensusRun.id.desc())
    for run in db.execute(stmt).scalars():
        if (run.metadata_json or {}).get('input_fingerprint') == input_fingerprint:
            return run
    return None


def insert_consensus_points(db: Session, points: Iterable[dict | ConsensusForecastPoint]) -> list[ConsensusForecastPoint]:
    rows = [p if isinstance(p, ConsensusForecastPoint) else ConsensusForecastPoint(created_at=p.pop('created_at', utc_now()), **p) for p in [dict(x) if isinstance(x, dict) else x for x in points]]
    db.add_all(rows)
    db.flush()
    return rows


def create_consensus_points(db: Session, points: Iterable[dict | ConsensusForecastPoint]) -> list[ConsensusForecastPoint]:
    return insert_consensus_points(db, points)


def list_consensus_points_for_run(db: Session, consensus_run_id: int) -> list[ConsensusForecastPoint]:
    return list(db.execute(select(ConsensusForecastPoint).where(ConsensusForecastPoint.consensus_run_id == consensus_run_id).order_by(ConsensusForecastPoint.spot_id, ConsensusForecastPoint.valid_at)).scalars())


def get_consensus_point(db: Session, point_id: int) -> ConsensusForecastPoint | None:
    return db.get(ConsensusForecastPoint, point_id)


def latest_consensus_runs(db: Session, limit: int = 10) -> list[ConsensusRun]:
    return list(db.execute(select(ConsensusRun).order_by(ConsensusRun.id.desc()).limit(limit)).scalars())
