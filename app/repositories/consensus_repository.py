from __future__ import annotations

from typing import Iterable

from sqlalchemy.orm import Session

from ..forecast_ledger_models import ConsensusForecastPoint, ConsensusRun
from .ledger_utils import utc_now


def create_consensus_run(db: Session, **values) -> ConsensusRun:
    row = ConsensusRun(created_at=values.pop('created_at', utc_now()), **values)
    db.add(row)
    db.flush()
    return row


def create_consensus_points(db: Session, points: Iterable[dict | ConsensusForecastPoint]) -> list[ConsensusForecastPoint]:
    rows = [p if isinstance(p, ConsensusForecastPoint) else ConsensusForecastPoint(created_at=p.pop('created_at', utc_now()), **p) for p in [dict(x) if isinstance(x, dict) else x for x in points]]
    db.add_all(rows)
    db.flush()
    return rows
