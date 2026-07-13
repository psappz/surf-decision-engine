from __future__ import annotations

from typing import Iterable

from sqlalchemy.orm import Session

from ..forecast_ledger_models import SpotAssessmentPoint, SpotAssessmentRun
from .ledger_utils import utc_now


def create_spot_assessment_run(db: Session, **values) -> SpotAssessmentRun:
    row = SpotAssessmentRun(created_at=values.pop('created_at', utc_now()), **values)
    db.add(row)
    db.flush()
    return row


def create_spot_assessment_points(db: Session, points: Iterable[dict | SpotAssessmentPoint]) -> list[SpotAssessmentPoint]:
    rows = [p if isinstance(p, SpotAssessmentPoint) else SpotAssessmentPoint(created_at=p.pop('created_at', utc_now()), **p) for p in [dict(x) if isinstance(x, dict) else x for x in points]]
    db.add_all(rows)
    db.flush()
    return rows
