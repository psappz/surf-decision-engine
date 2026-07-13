from __future__ import annotations

from datetime import datetime
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..forecast_ledger_models import ForecastRun, ProviderForecastPoint
from .ledger_utils import utc_now


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
