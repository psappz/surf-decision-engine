from __future__ import annotations

from typing import Iterable

from sqlalchemy.orm import Session

from ..forecast_ledger_models import SpotScoreRun, SpotScoreSnapshot
from .ledger_utils import utc_now


def create_spot_score_run(db: Session, **values) -> SpotScoreRun:
    row = SpotScoreRun(created_at=values.pop('created_at', utc_now()), **values)
    db.add(row)
    db.flush()
    return row


def create_spot_score_snapshots(db: Session, snapshots: Iterable[dict | SpotScoreSnapshot]) -> list[SpotScoreSnapshot]:
    rows = [s if isinstance(s, SpotScoreSnapshot) else SpotScoreSnapshot(created_at=s.pop('created_at', utc_now()), **s) for s in [dict(x) if isinstance(x, dict) else x for x in snapshots]]
    db.add_all(rows)
    db.flush()
    return rows
