from __future__ import annotations

from typing import Iterable

from sqlalchemy.orm import Session

from ..forecast_ledger_models import ConfidenceRun, ConfidenceSnapshot
from .ledger_utils import utc_now


def create_confidence_run(db: Session, **values) -> ConfidenceRun:
    row = ConfidenceRun(created_at=values.pop('created_at', utc_now()), **values)
    db.add(row)
    db.flush()
    return row


def create_confidence_snapshots(db: Session, snapshots: Iterable[dict | ConfidenceSnapshot]) -> list[ConfidenceSnapshot]:
    rows = [s if isinstance(s, ConfidenceSnapshot) else ConfidenceSnapshot(created_at=s.pop('created_at', utc_now()), **s) for s in [dict(x) if isinstance(x, dict) else x for x in snapshots]]
    db.add_all(rows)
    db.flush()
    return rows
