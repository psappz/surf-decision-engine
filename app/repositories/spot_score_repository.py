from __future__ import annotations

from typing import Iterable

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..forecast_ledger_models import (
    SpotAssessmentPoint,
    SpotAssessmentRun,
    SpotScoreRun,
    SpotScoreSnapshot,
)
from ..services.consensus_safety import redact_text
from .ledger_utils import utc_now

MAX_LIST_LIMIT = 500


class SpotScoreRunTransitionError(RuntimeError):
    """Raised when an append-only score-run lifecycle rule is violated."""


def create_spot_score_run(db: Session, **values) -> SpotScoreRun:
    if values.get('status', 'running') != 'running':
        raise SpotScoreRunTransitionError('spot score runs must be created in running state')
    values['status'] = 'running'
    assessment_run_id = _integer_id('assessment_run_id', values.get('assessment_run_id'))
    assessment_run = db.get(SpotAssessmentRun, assessment_run_id)
    if assessment_run is None or assessment_run.status != 'completed':
        raise SpotScoreRunTransitionError(
            'spot score runs require an existing completed assessment run'
        )
    values['assessment_run_id'] = assessment_run_id
    sequence = values.setdefault('recalculation_sequence', 0)
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        raise SpotScoreRunTransitionError('recalculation_sequence must be a non-negative integer')
    scope_hash = values.setdefault('calculation_scope_hash', 'legacy-unscoped')
    if not isinstance(scope_hash, str) or not scope_hash or len(scope_hash) > 128:
        raise SpotScoreRunTransitionError(
            'calculation_scope_hash must be a non-empty string of at most 128 characters'
        )
    values.setdefault('created_at', utc_now())
    row = SpotScoreRun(**values)
    db.add(row)
    db.flush()
    return row


def get_spot_score_run(db: Session, run_id: int) -> SpotScoreRun | None:
    return db.get(SpotScoreRun, run_id)


def mark_spot_score_run_status(
    db: Session,
    run_id: int,
    status: str,
    *,
    error_message: str | None = None,
    metadata_json: dict | None = None,
) -> SpotScoreRun:
    if status not in {'completed', 'failed'}:
        raise SpotScoreRunTransitionError('only running -> completed|failed transitions are allowed')
    values: dict = {'status': status}
    if error_message is not None:
        values['error_message'] = redact_text(error_message, max_length=1000)
    if metadata_json is not None:
        values['metadata_json'] = metadata_json
    result = db.execute(
        update(SpotScoreRun)
        .where(SpotScoreRun.id == run_id, SpotScoreRun.status == 'running')
        .values(**values)
    )
    if result.rowcount != 1:
        raise SpotScoreRunTransitionError(f'score run {run_id} does not exist in running state')
    db.flush()
    row = db.get(SpotScoreRun, run_id)
    if row is None:
        raise SpotScoreRunTransitionError(f'score run {run_id} disappeared during transition')
    db.refresh(row)
    return row


def create_spot_score_snapshots(
    db: Session,
    snapshots: Iterable[dict | SpotScoreSnapshot],
) -> list[SpotScoreSnapshot]:
    values = list(snapshots)
    if not values:
        return []
    try:
        run_ids = {
            _integer_id(
                'score_run_id',
                item.score_run_id if isinstance(item, SpotScoreSnapshot) else item['score_run_id'],
            )
            for item in values
        }
    except (KeyError, TypeError) as exc:
        raise SpotScoreRunTransitionError(
            'every score snapshot must reference a typed score run id'
        ) from exc
    if len(run_ids) != 1:
        raise SpotScoreRunTransitionError('snapshot batches must target exactly one score run')
    run = db.get(SpotScoreRun, next(iter(run_ids)))
    if run is None or run.status != 'running':
        raise SpotScoreRunTransitionError('score snapshots may only be inserted into an existing running run')

    rows: list[SpotScoreSnapshot] = []
    assessment_ids: set[int] = set()
    for item in values:
        row = item if isinstance(item, SpotScoreSnapshot) else SpotScoreSnapshot(
            **({'created_at': utc_now()} | dict(item))
        )
        point_id = _integer_id('assessment_point_id', row.assessment_point_id)
        if point_id in assessment_ids:
            raise SpotScoreRunTransitionError('a snapshot batch may reference each assessment point only once')
        assessment_ids.add(point_id)
        point = db.get(SpotAssessmentPoint, point_id)
        if point is None or point.assessment_run_id != run.assessment_run_id:
            raise SpotScoreRunTransitionError('assessment point does not belong to the score run input')
        if point.spot_id != row.spot_id or point.valid_at != row.valid_at:
            raise SpotScoreRunTransitionError('snapshot identity must match its assessment point')
        rows.append(row)
    db.add_all(rows)
    db.flush()
    return rows


def find_equivalent_completed_score(
    db: Session,
    *,
    assessment_run_id: int,
    engine_version: str,
    configuration_hash: str,
    profile_version: str,
    profile_hash: str,
    scope_hash: str,
) -> SpotScoreRun | None:
    stmt = _equivalent_query(
        assessment_run_id=assessment_run_id,
        engine_version=engine_version,
        configuration_hash=configuration_hash,
        profile_version=profile_version,
        profile_hash=profile_hash,
        scope_hash=scope_hash,
    ).where(SpotScoreRun.status == 'completed').order_by(
        SpotScoreRun.calculated_at.desc(), SpotScoreRun.id.desc()
    ).limit(1)
    return db.scalar(stmt)


def find_latest_equivalent_score(
    db: Session,
    *,
    assessment_run_id: int,
    engine_version: str,
    configuration_hash: str,
    profile_version: str,
    profile_hash: str,
    scope_hash: str,
) -> SpotScoreRun | None:
    stmt = _equivalent_query(
        assessment_run_id=assessment_run_id,
        engine_version=engine_version,
        configuration_hash=configuration_hash,
        profile_version=profile_version,
        profile_hash=profile_hash,
        scope_hash=scope_hash,
    ).order_by(SpotScoreRun.recalculation_sequence.desc(), SpotScoreRun.id.desc()).limit(1)
    return db.scalar(stmt)


def next_spot_score_recalculation_sequence(
    db: Session,
    *,
    assessment_run_id: int,
    engine_version: str,
    configuration_hash: str,
    profile_version: str,
    profile_hash: str,
    scope_hash: str,
) -> int:
    conditions = _equivalent_conditions(
        assessment_run_id, engine_version, configuration_hash,
        profile_version, profile_hash, scope_hash,
    )
    value = db.scalar(select(func.max(SpotScoreRun.recalculation_sequence)).where(*conditions))
    return int(value or 0) + 1


def get_spot_score_snapshot(db: Session, snapshot_id: int) -> SpotScoreSnapshot | None:
    return db.get(SpotScoreSnapshot, snapshot_id)


def count_spot_score_snapshots_for_run(db: Session, run_id: int) -> int:
    return int(db.scalar(
        select(func.count()).select_from(SpotScoreSnapshot)
        .where(SpotScoreSnapshot.score_run_id == run_id)
    ) or 0)


def list_spot_score_snapshots_for_run(
    db: Session,
    run_id: int,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[SpotScoreSnapshot]:
    limit, offset = _bounded_page(limit, offset)
    stmt = select(SpotScoreSnapshot).where(
        SpotScoreSnapshot.score_run_id == run_id
    ).order_by(
        SpotScoreSnapshot.valid_at, SpotScoreSnapshot.spot_id, SpotScoreSnapshot.id
    ).limit(limit).offset(offset)
    return list(db.scalars(stmt))


def count_spot_score_runs(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(SpotScoreRun)) or 0)


def latest_spot_score_runs(
    db: Session,
    *,
    limit: int = 20,
    offset: int = 0,
) -> list[SpotScoreRun]:
    limit, offset = _bounded_page(limit, offset)
    return list(db.scalars(
        select(SpotScoreRun).order_by(
            SpotScoreRun.calculated_at.desc(), SpotScoreRun.id.desc()
        ).limit(limit).offset(offset)
    ))


def _bounded_page(limit: int, offset: int) -> tuple[int, int]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIST_LIMIT:
        raise ValueError(f'limit must be an integer in 1..{MAX_LIST_LIMIT}')
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError('offset must be a non-negative integer')
    return limit, offset


def _integer_id(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SpotScoreRunTransitionError(f'{name} must be a positive integer')
    return value


def _equivalent_query(**values):
    return select(SpotScoreRun).where(*_equivalent_conditions(
        values['assessment_run_id'], values['engine_version'], values['configuration_hash'],
        values['profile_version'], values['profile_hash'], values['scope_hash'],
    ))


def _equivalent_conditions(
    assessment_run_id: int,
    engine_version: str,
    configuration_hash: str,
    profile_version: str,
    profile_hash: str,
    scope_hash: str,
):
    return (
        SpotScoreRun.assessment_run_id == assessment_run_id,
        SpotScoreRun.scoring_engine_version == engine_version,
        SpotScoreRun.scoring_configuration_hash == configuration_hash,
        SpotScoreRun.surfer_profile_version == profile_version,
        SpotScoreRun.surfer_profile_hash == profile_hash,
        SpotScoreRun.calculation_scope_hash == scope_hash,
    )
