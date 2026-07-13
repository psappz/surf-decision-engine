from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ProviderFetch
from .forecast_ledger_models import (
    ConfidenceRun,
    ConfidenceSnapshot,
    ConsensusForecastPoint,
    ConsensusRun,
    ForecastRun,
    ProviderForecastPoint,
    ProviderPublication,
    RecommendationSnapshot,
    SpotAssessmentPoint,
    SpotAssessmentRun,
    SpotScoreRun,
    SpotScoreSnapshot,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def create_publication(db: Session, **values) -> ProviderPublication:
    now = values.pop('now', utc_now())
    publication = ProviderPublication(created_at=now, updated_at=now, **values)
    db.add(publication)
    db.flush()
    return publication


def get_publication_by_identity(db: Session, provider_name: str, dataset_id: str | None, publication_identity: str) -> ProviderPublication | None:
    return db.execute(
        select(ProviderPublication).where(
            ProviderPublication.provider_name == provider_name,
            ProviderPublication.dataset_id == (dataset_id or ''),
            ProviderPublication.publication_identity == publication_identity,
        )
    ).scalar_one_or_none()


def list_publications(db: Session, provider_name: str | None = None, status: str | None = None) -> list[ProviderPublication]:
    stmt = select(ProviderPublication).order_by(ProviderPublication.detected_at.desc(), ProviderPublication.id.desc())
    if provider_name:
        stmt = stmt.where(ProviderPublication.provider_name == provider_name)
    if status:
        stmt = stmt.where(ProviderPublication.status == status)
    return list(db.execute(stmt).scalars())


def create_fetch_attempt(db: Session, publication_id: int, attempt_number: int, **values) -> ProviderFetch:
    now = values.pop('now', utc_now())
    fetch = ProviderFetch(
        publication_id=publication_id,
        attempt_number=attempt_number,
        provider_name=values.pop('provider_name'),
        fetched_at=values.pop('fetched_at', now),
        latitude=values.pop('latitude', None),
        longitude=values.pop('longitude', None),
        raw_response=values.pop('raw_response', None),
        parsing_errors=values.pop('parsing_errors', None),
        data_age_seconds=values.pop('data_age_seconds', None),
        started_at=values.pop('started_at', now),
        created_at=now,
        updated_at=now,
        **values,
    )
    db.add(fetch)
    db.flush()
    return fetch


def mark_fetch_status(db: Session, fetch_id: int, status: str, **values) -> ProviderFetch:
    fetch = db.get(ProviderFetch, fetch_id)
    if fetch is None:
        raise ValueError(f'provider fetch {fetch_id} not found')
    fetch.status = status
    fetch.updated_at = values.pop('updated_at', utc_now())
    for key, value in values.items():
        setattr(fetch, key, value)
    db.flush()
    return fetch


def create_forecast_run(db: Session, **values) -> ForecastRun:
    run = ForecastRun(created_at=values.pop('created_at', utc_now()), **values)
    db.add(run)
    db.flush()
    return run


def get_forecast_run(db: Session, forecast_run_id: int) -> ForecastRun | None:
    return db.get(ForecastRun, forecast_run_id)


def _point(values: dict) -> ProviderForecastPoint:
    data = dict(values)
    data['sample_point_id'] = data.get('sample_point_id') or ''
    data.setdefault('created_at', utc_now())
    return ProviderForecastPoint(**data)


def insert_forecast_points(db: Session, points: Iterable[dict | ProviderForecastPoint]) -> list[ProviderForecastPoint]:
    rows = [p if isinstance(p, ProviderForecastPoint) else _point(p) for p in points]
    db.add_all(rows)
    db.flush()
    return rows


def list_points_for_run(db: Session, forecast_run_id: int) -> list[ProviderForecastPoint]:
    return list(db.execute(select(ProviderForecastPoint).where(ProviderForecastPoint.forecast_run_id == forecast_run_id).order_by(ProviderForecastPoint.valid_at, ProviderForecastPoint.spot_id)).scalars())


def list_versions_for_spot_and_valid_time(db: Session, spot_id: int, valid_at: datetime) -> list[ProviderForecastPoint]:
    return list(db.execute(select(ProviderForecastPoint).where(ProviderForecastPoint.spot_id == spot_id, ProviderForecastPoint.valid_at == valid_at).order_by(ProviderForecastPoint.forecast_run_id)).scalars())


def create_consensus_run(db: Session, **values) -> ConsensusRun:
    row = ConsensusRun(created_at=values.pop('created_at', utc_now()), **values)
    db.add(row); db.flush(); return row


def create_consensus_points(db: Session, points: Iterable[dict | ConsensusForecastPoint]) -> list[ConsensusForecastPoint]:
    rows = [p if isinstance(p, ConsensusForecastPoint) else ConsensusForecastPoint(created_at=p.pop('created_at', utc_now()), **p) for p in [dict(x) if isinstance(x, dict) else x for x in points]]
    db.add_all(rows); db.flush(); return rows


def create_spot_assessment_run(db: Session, **values) -> SpotAssessmentRun:
    row = SpotAssessmentRun(created_at=values.pop('created_at', utc_now()), **values)
    db.add(row); db.flush(); return row


def create_spot_assessment_points(db: Session, points: Iterable[dict | SpotAssessmentPoint]) -> list[SpotAssessmentPoint]:
    rows = [p if isinstance(p, SpotAssessmentPoint) else SpotAssessmentPoint(created_at=p.pop('created_at', utc_now()), **p) for p in [dict(x) if isinstance(x, dict) else x for x in points]]
    db.add_all(rows); db.flush(); return rows


def create_spot_score_run(db: Session, **values) -> SpotScoreRun:
    row = SpotScoreRun(created_at=values.pop('created_at', utc_now()), **values)
    db.add(row); db.flush(); return row


def create_spot_score_snapshots(db: Session, snapshots: Iterable[dict | SpotScoreSnapshot]) -> list[SpotScoreSnapshot]:
    rows = [s if isinstance(s, SpotScoreSnapshot) else SpotScoreSnapshot(created_at=s.pop('created_at', utc_now()), **s) for s in [dict(x) if isinstance(x, dict) else x for x in snapshots]]
    db.add_all(rows); db.flush(); return rows


def create_confidence_run(db: Session, **values) -> ConfidenceRun:
    row = ConfidenceRun(created_at=values.pop('created_at', utc_now()), **values)
    db.add(row); db.flush(); return row


def create_confidence_snapshots(db: Session, snapshots: Iterable[dict | ConfidenceSnapshot]) -> list[ConfidenceSnapshot]:
    rows = [s if isinstance(s, ConfidenceSnapshot) else ConfidenceSnapshot(created_at=s.pop('created_at', utc_now()), **s) for s in [dict(x) if isinstance(x, dict) else x for x in snapshots]]
    db.add_all(rows); db.flush(); return rows


def create_recommendation_snapshot(db: Session, **values) -> RecommendationSnapshot:
    row = RecommendationSnapshot(created_at=values.pop('created_at', utc_now()), **values)
    db.add(row); db.flush(); return row


def list_recommendation_versions(db: Session, recommendation_date, daypart: str) -> list[RecommendationSnapshot]:
    return list(db.execute(select(RecommendationSnapshot).where(RecommendationSnapshot.recommendation_date == recommendation_date, RecommendationSnapshot.daypart == daypart).order_by(RecommendationSnapshot.generated_at, RecommendationSnapshot.id)).scalars())
