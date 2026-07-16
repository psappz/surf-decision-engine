from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime
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
from ..services.spot_scoring_configuration import (
    SpotScoringConfiguration,
    SurferProfileSnapshot,
    canonical_payload_hash,
)
from .ledger_utils import utc_now

MAX_LIST_LIMIT = 500
MAX_SCOPE_POINTS = 10_000
MAX_JSON_BYTES = 64_000
_IDENTIFIER = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$')
_HASH = re.compile(r'^[a-f0-9]{64}$')
_COMPONENT_FIELDS = (
    'swell_direction_score', 'swell_height_score', 'period_score',
    'wind_direction_score', 'wind_speed_score', 'tide_score', 'safety_score',
)
_SNAPSHOT_FIELDS = {
    'score_run_id', 'assessment_point_id', 'spot_id', 'valid_at', 'total_score',
    'condition_classification', *_COMPONENT_FIELDS, 'penalty_total',
    'penalties_json', 'positive_factors_json', 'negative_factors_json',
}


class SpotScoreRunTransitionError(RuntimeError):
    """Raised when an append-only score-run lifecycle rule is violated."""


def create_spot_score_run(
    db: Session,
    *,
    assessment_run_id: int,
    calculated_at: datetime,
    scoring_configuration: SpotScoringConfiguration,
    surfer_profile: SurferProfileSnapshot,
    assessment_point_ids: Iterable[int],
    recalculation_sequence: int = 0,
) -> SpotScoreRun:
    assessment_run_id = _integer_id('assessment_run_id', assessment_run_id)
    assessment_run = db.get(SpotAssessmentRun, assessment_run_id)
    if assessment_run is None or assessment_run.status != 'completed':
        raise SpotScoreRunTransitionError(
            'spot score runs require an existing completed assessment run'
        )
    if not isinstance(scoring_configuration, SpotScoringConfiguration):
        raise SpotScoreRunTransitionError('scoring_configuration must be a validated snapshot')
    if not isinstance(surfer_profile, SurferProfileSnapshot):
        raise SpotScoreRunTransitionError('surfer_profile must be a validated snapshot')
    config = scoring_configuration.canonicalized()
    profile = surfer_profile.canonicalized()
    config.validate()
    profile.validate()
    sequence = _nonnegative_integer('recalculation_sequence', recalculation_sequence)
    scope = _canonical_scope(assessment_point_ids)
    existing_points = set(db.scalars(
        select(SpotAssessmentPoint.id).where(
            SpotAssessmentPoint.assessment_run_id == assessment_run_id,
            SpotAssessmentPoint.id.in_(scope),
        )
    ))
    if existing_points != set(scope):
        raise SpotScoreRunTransitionError(
            'calculation scope must contain only assessment points from the score run input'
        )
    config_payload = config.canonical_payload()
    profile_payload = profile.canonical_payload()
    scope_payload = {'assessment_point_ids': scope}
    row = SpotScoreRun(
        assessment_run_id=assessment_run_id,
        calculated_at=_timestamp('calculated_at', calculated_at),
        scoring_engine_version=_identifier('scoring engine version', config.engine_version),
        scoring_configuration_hash=canonical_payload_hash(config_payload),
        scoring_configuration_json=_bounded_json('scoring configuration', config_payload),
        surfer_profile_name=_identifier('surfer profile name', profile.profile_name),
        surfer_profile_version=_identifier('surfer profile version', profile.version),
        surfer_profile_hash=canonical_payload_hash(profile_payload),
        surfer_profile_json=_bounded_json('surfer profile', profile_payload),
        calculation_scope_hash=canonical_payload_hash(scope_payload),
        calculation_scope_json=scope,
        recalculation_sequence=sequence,
        status='running',
        created_at=utc_now(),
    )
    db.add(row)
    db.flush()
    return row


def get_spot_score_run(db: Session, run_id: int) -> SpotScoreRun | None:
    return db.get(SpotScoreRun, _integer_id('run_id', run_id))


def mark_spot_score_run_status(
    db: Session,
    run_id: int,
    status: str,
    *,
    error_message: str | None = None,
    metadata_json: dict | None = None,
) -> SpotScoreRun:
    run_id = _integer_id('run_id', run_id)
    if status not in {'completed', 'failed'}:
        raise SpotScoreRunTransitionError('only running -> completed|failed transitions are allowed')
    _lock_running_run(db, run_id)
    if status == 'completed':
        run = db.get(SpotScoreRun, run_id)
        expected = _stored_scope(run.calculation_scope_json if run else None)
        actual = set(db.scalars(select(SpotScoreSnapshot.assessment_point_id).where(
            SpotScoreSnapshot.score_run_id == run_id
        )))
        if actual != set(expected):
            raise SpotScoreRunTransitionError(
                f'score run {run_id} cannot complete until snapshots exactly cover its canonical scope'
            )
    values: dict = {'status': status}
    if error_message is not None:
        if not isinstance(error_message, str):
            raise SpotScoreRunTransitionError('error_message must be text')
        values['error_message'] = redact_text(error_message, max_length=1000)
    if metadata_json is not None:
        values['metadata_json'] = _bounded_json('metadata_json', _sanitize_json(metadata_json))
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
        raise SpotScoreRunTransitionError('snapshot batches must not be empty')
    if len(values) > MAX_SCOPE_POINTS:
        raise SpotScoreRunTransitionError(f'snapshot batches may contain at most {MAX_SCOPE_POINTS} rows')
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
    run_id = next(iter(run_ids))
    _lock_running_run(db, run_id)
    run = db.get(SpotScoreRun, run_id)
    if run is None:
        raise SpotScoreRunTransitionError('score snapshots require an existing running run')
    scope = set(_stored_scope(run.calculation_scope_json))

    rows: list[SpotScoreSnapshot] = []
    assessment_ids: set[int] = set()
    for item in values:
        if isinstance(item, SpotScoreSnapshot):
            raw = {field: getattr(item, field) for field in _SNAPSHOT_FIELDS}
        else:
            raw = dict(item)
            unknown = set(raw) - _SNAPSHOT_FIELDS
            if unknown:
                raise SpotScoreRunTransitionError(f'unsupported snapshot fields: {sorted(unknown)!r}')
        point_id = _integer_id('assessment_point_id', raw.get('assessment_point_id'))
        if point_id in assessment_ids:
            raise SpotScoreRunTransitionError('a snapshot batch may reference each assessment point only once')
        if point_id not in scope:
            raise SpotScoreRunTransitionError('assessment point is outside the score run canonical scope')
        assessment_ids.add(point_id)
        point = db.get(SpotAssessmentPoint, point_id)
        if point is None or point.assessment_run_id != run.assessment_run_id:
            raise SpotScoreRunTransitionError('assessment point does not belong to the score run input')
        spot_id = _integer_id('spot_id', raw.get('spot_id'))
        raw_valid_at = raw.get('valid_at')
        if not isinstance(raw_valid_at, datetime):
            raise SpotScoreRunTransitionError('valid_at must be a datetime')
        # ORM-loaded SQLite values are naive despite timezone=True; interpret
        # that dialect representation as UTC before identity comparison/storage.
        valid_at = _utc_value(raw_valid_at)
        if point.spot_id != spot_id or _utc_value(point.valid_at) != valid_at:
            raise SpotScoreRunTransitionError('snapshot identity must match its assessment point')
        prepared = {
            'score_run_id': run_id,
            'assessment_point_id': point_id,
            'spot_id': spot_id,
            'valid_at': valid_at,
            'total_score': _score('total_score', raw.get('total_score')),
            'condition_classification': _bounded_text(
                'condition_classification', raw.get('condition_classification'), 80
            ),
            'created_at': utc_now(),
        }
        for field in _COMPONENT_FIELDS:
            prepared[field] = _optional_score(field, raw.get(field))
        prepared['penalty_total'] = _optional_score('penalty_total', raw.get('penalty_total'))
        for field in ('penalties_json', 'positive_factors_json', 'negative_factors_json'):
            payload = raw.get(field)
            prepared[field] = None if payload is None else _bounded_json(field, _sanitize_json(payload))
        rows.append(SpotScoreSnapshot(**prepared))
    db.add_all(rows)
    db.flush()
    return rows


def find_equivalent_completed_score(db: Session, **values) -> SpotScoreRun | None:
    stmt = _equivalent_query(**values).where(SpotScoreRun.status == 'completed').order_by(
        SpotScoreRun.calculated_at.desc(), SpotScoreRun.id.desc()
    ).limit(1)
    return db.scalar(stmt)


def find_latest_equivalent_score(db: Session, **values) -> SpotScoreRun | None:
    stmt = _equivalent_query(**values).order_by(
        SpotScoreRun.recalculation_sequence.desc(), SpotScoreRun.id.desc()
    ).limit(1)
    return db.scalar(stmt)


def next_spot_score_recalculation_sequence(db: Session, **values) -> int:
    conditions = _equivalent_conditions_from_values(values)
    value = db.scalar(select(func.max(SpotScoreRun.recalculation_sequence)).where(*conditions))
    return int(value or 0) + 1


def get_spot_score_snapshot(db: Session, snapshot_id: int) -> SpotScoreSnapshot | None:
    return db.get(SpotScoreSnapshot, _integer_id('snapshot_id', snapshot_id))


def count_spot_score_snapshots_for_run(db: Session, run_id: int) -> int:
    run_id = _integer_id('run_id', run_id)
    return int(db.scalar(select(func.count()).select_from(SpotScoreSnapshot).where(
        SpotScoreSnapshot.score_run_id == run_id
    )) or 0)


def list_spot_score_snapshots_for_run(
    db: Session, run_id: int, *, limit: int = 100, offset: int = 0,
) -> list[SpotScoreSnapshot]:
    run_id = _integer_id('run_id', run_id)
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
    db: Session, *, limit: int = 20, offset: int = 0,
) -> list[SpotScoreRun]:
    limit, offset = _bounded_page(limit, offset)
    return list(db.scalars(select(SpotScoreRun).order_by(
        SpotScoreRun.calculated_at.desc(), SpotScoreRun.id.desc()
    ).limit(limit).offset(offset)))


def _lock_running_run(db: Session, run_id: int) -> None:
    # A conditional no-op write serializes SQLite sessions and locks the selected
    # row on PostgreSQL. Completion and insertion therefore share one write gate.
    result = db.execute(update(SpotScoreRun).where(
        SpotScoreRun.id == run_id, SpotScoreRun.status == 'running'
    ).values(status='running'))
    if result.rowcount != 1:
        raise SpotScoreRunTransitionError(f'score run {run_id} does not exist in running state')
    db.flush()


def _canonical_scope(values: Iterable[int]) -> list[int]:
    if isinstance(values, (str, bytes)):
        raise SpotScoreRunTransitionError('assessment_point_ids must be an iterable of ids')
    try:
        scope = [_integer_id('assessment_point_id', value) for value in values]
    except TypeError as exc:
        raise SpotScoreRunTransitionError('assessment_point_ids must be an iterable of ids') from exc
    if not scope:
        raise SpotScoreRunTransitionError('calculation scope must not be empty')
    if len(scope) > MAX_SCOPE_POINTS:
        raise SpotScoreRunTransitionError(f'calculation scope may contain at most {MAX_SCOPE_POINTS} points')
    if len(scope) != len(set(scope)):
        raise SpotScoreRunTransitionError('calculation scope must not contain duplicate points')
    return sorted(scope)


def _stored_scope(value: object) -> list[int]:
    if not isinstance(value, list):
        raise SpotScoreRunTransitionError('stored calculation scope is invalid')
    scope = _canonical_scope(value)
    if scope != value:
        raise SpotScoreRunTransitionError('stored calculation scope is not canonical')
    return scope


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


def _nonnegative_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SpotScoreRunTransitionError(f'{name} must be a non-negative integer')
    return value


def _identifier(name: str, value: object) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise SpotScoreRunTransitionError(f'{name} must be a valid identifier of at most 80 characters')
    return value


def _hash(name: str, value: object) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ValueError(f'{name} must be a lowercase SHA-256 digest')
    return value


def _timestamp(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise SpotScoreRunTransitionError(f'{name} must be a timezone-aware datetime')
    return value.astimezone(UTC)


def _utc_value(value: datetime) -> datetime:
    # SQLite returns naive datetimes even for timezone=True columns.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _score(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SpotScoreRunTransitionError(f'{name} must be a number within 0..100')
    number = float(value)
    if not 0 <= number <= 100:
        raise SpotScoreRunTransitionError(f'{name} must be a number within 0..100')
    return 0.0 if number == 0 else number


def _optional_score(name: str, value: object) -> float | None:
    return None if value is None else _score(name, value)


def _bounded_text(name: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise SpotScoreRunTransitionError(f'{name} must be non-empty safe text of at most {maximum} characters')
    return value


def _sanitize_json(value: object, *, depth: int = 0) -> object:
    if depth > 8:
        raise SpotScoreRunTransitionError('JSON payload nesting exceeds 8 levels')
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SpotScoreRunTransitionError('JSON numeric values must be finite')
        return 0.0 if value == 0 else value
    if isinstance(value, str):
        return redact_text(value, max_length=1000)
    if isinstance(value, list):
        if len(value) > 1000:
            raise SpotScoreRunTransitionError('JSON arrays may contain at most 1000 items')
        return [_sanitize_json(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > 200:
            raise SpotScoreRunTransitionError('JSON objects may contain at most 200 keys')
        result = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 100:
                raise SpotScoreRunTransitionError('JSON object keys must be non-empty text up to 100 characters')
            result[key] = _sanitize_json(item, depth=depth + 1)
        return result
    raise SpotScoreRunTransitionError('JSON payload contains an unsupported value')


def _bounded_json(name: str, value: object):
    try:
        size = len(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode())
    except (TypeError, ValueError) as exc:
        raise SpotScoreRunTransitionError(f'{name} must be JSON serializable') from exc
    if size > MAX_JSON_BYTES:
        raise SpotScoreRunTransitionError(f'{name} must not exceed {MAX_JSON_BYTES} bytes')
    return value


def _equivalent_query(**values):
    return select(SpotScoreRun).where(*_equivalent_conditions_from_values(values))


def _equivalent_conditions_from_values(values: dict):
    return (
        SpotScoreRun.assessment_run_id == _integer_id('assessment_run_id', values['assessment_run_id']),
        SpotScoreRun.scoring_engine_version == _identifier('engine_version', values['engine_version']),
        SpotScoreRun.scoring_configuration_hash == _hash('configuration_hash', values['configuration_hash']),
        SpotScoreRun.surfer_profile_version == _identifier('profile_version', values['profile_version']),
        SpotScoreRun.surfer_profile_hash == _hash('profile_hash', values['profile_hash']),
        SpotScoreRun.calculation_scope_hash == _hash('scope_hash', values['scope_hash']),
    )
