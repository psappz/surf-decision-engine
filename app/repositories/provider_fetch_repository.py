from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import ProviderFetch
from .ledger_utils import utc_now


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
