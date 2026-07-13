from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..forecast_ledger_models import RecommendationSnapshot
from .ledger_utils import utc_now


def create_recommendation_snapshot(db: Session, **values) -> RecommendationSnapshot:
    row = RecommendationSnapshot(created_at=values.pop('created_at', utc_now()), **values)
    db.add(row)
    db.flush()
    return row


def list_recommendation_versions(db: Session, recommendation_date, daypart: str) -> list[RecommendationSnapshot]:
    return list(db.execute(select(RecommendationSnapshot).where(RecommendationSnapshot.recommendation_date == recommendation_date, RecommendationSnapshot.daypart == daypart).order_by(RecommendationSnapshot.generated_at, RecommendationSnapshot.id)).scalars())
