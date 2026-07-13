from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..forecast_ledger_models import ProviderPublication
from .ledger_utils import utc_now


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
