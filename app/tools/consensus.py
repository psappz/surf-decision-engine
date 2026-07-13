from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Sequence

from ..database import SessionLocal
from ..repositories.consensus_repository import count_consensus_points_for_run, get_consensus_point, get_consensus_run, latest_consensus_runs, list_consensus_points_for_run
from ..services.consensus_configuration import default_consensus_configuration
from ..services.consensus_engine import ConsensusCalculationRequest, ConsensusEngine, calculate_latest
from ..services.consensus_safety import bounded_json, redact_text


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _datetime_arg(value: str) -> datetime:
    try:
        return parse_utc(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f'invalid ISO-8601 timestamp: {value}') from exc


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError('must be a positive integer')
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError('must be a non-negative integer')
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='python -m app.tools.consensus')
    sub = parser.add_subparsers(dest='command', required=True)
    latest = sub.add_parser('calculate-latest')
    latest.add_argument('--hours', type=_nonnegative_int, default=72)
    latest.add_argument('--spot-id', action='append', type=_positive_int)
    latest.add_argument('--force', action='store_true')
    latest.add_argument('--dry-run', action='store_true')
    calculate = sub.add_parser('calculate')
    calculate.add_argument('--cutoff', required=True, type=_datetime_arg)
    calculate.add_argument('--valid-from', required=True, type=_datetime_arg)
    calculate.add_argument('--valid-until', required=True, type=_datetime_arg)
    calculate.add_argument('--spot-id', action='append', type=_positive_int)
    calculate.add_argument('--force', action='store_true')
    calculate.add_argument('--dry-run', action='store_true')
    status = sub.add_parser('status')
    status.add_argument('--limit', type=_positive_int, default=10)
    inspect = sub.add_parser('inspect-run')
    inspect.add_argument('run_id', type=_positive_int)
    inspect.add_argument('--limit', type=_positive_int, default=50)
    explain = sub.add_parser('explain-point')
    explain.add_argument('point_id', type=_positive_int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == 'calculate' and args.valid_from > args.valid_until:
        parser.error('--valid-from must not be after --valid-until')
    db = SessionLocal()
    try:
        if args.command == 'status':
            payload = []
            for run in latest_consensus_runs(db, limit=min(args.limit, 100)):
                summary = _run_summary(run)
                summary['point_count'] = count_consensus_points_for_run(db, run.id)
                payload.append(summary)
            _print_json(payload)
            return 0
        if args.command == 'inspect-run':
            run = get_consensus_run(db, args.run_id)
            if run is None:
                _print_json({'error': 'consensus_run_not_found', 'run_id': args.run_id})
                return 2
            total = count_consensus_points_for_run(db, run.id)
            points = list_consensus_points_for_run(db, run.id, limit=min(args.limit, 100))
            _print_json({'run': _run_summary(run), 'point_count': total, 'returned_point_count': len(points), 'truncated': total > len(points), 'points': [_point_summary(point) for point in points]})
            return 0
        if args.command == 'explain-point':
            point = get_consensus_point(db, args.point_id)
            if point is None:
                _print_json({'error': 'consensus_point_not_found', 'point_id': args.point_id})
                return 2
            run = get_consensus_run(db, point.consensus_run_id)
            _print_json({'point': _point_summary(point), 'run': _run_summary(run) if run else None, 'calculation_details': bounded_json(point.calculation_details_json)})
            return 0
        spot_ids = tuple(sorted(set(args.spot_id))) if args.spot_id else None
        if args.command == 'calculate-latest':
            result = calculate_latest(db, hours=args.hours, spot_ids=spot_ids, force=args.force, dry_run=args.dry_run)
        else:
            configuration = default_consensus_configuration()
            result = ConsensusEngine(db).calculate(ConsensusCalculationRequest(args.cutoff, args.valid_from, args.valid_until, spot_ids, configuration.engine_version, configuration, 'manual_cli', force_recalculation=args.force, dry_run=args.dry_run))
        _print_json(asdict(result))
        return 0
    except ValueError as exc:
        _print_json({'error': 'invalid_request', 'message': redact_text(exc, max_length=300)})
        return 2
    except Exception as exc:
        _print_json({'error': 'consensus_command_failed', 'message': redact_text(exc, max_length=500)})
        return 1
    finally:
        db.close()


def _run_summary(run) -> dict:
    return bounded_json({
        'id': run.id,
        'status': run.status,
        'calculated_at': run.calculated_at.isoformat(),
        'forecast_cutoff_at': run.forecast_cutoff_at.isoformat(),
        'engine_version': run.consensus_engine_version,
        'configuration_hash': run.configuration_hash,
        'error_message': redact_text(run.error_message, max_length=1000) if run.error_message else None,
        'metadata': run.metadata_json,
    }, max_bytes=16_384)


def _point_summary(point) -> dict:
    return {
        'id': point.id,
        'consensus_run_id': point.consensus_run_id,
        'spot_id': point.spot_id,
        'valid_at': point.valid_at.isoformat(),
        'provider_count': point.provider_count,
        'agreement_score': point.agreement_score,
        'freshness_score': point.freshness_score,
        'completeness_score': point.completeness_score,
        'confidence_input_score': point.confidence_input_score,
    }


def _print_json(value) -> None:
    # Commands cap result sets at 100; preserve that pagination exactly instead
    # of applying the generic 24-item JSON limit a second time.
    print(json.dumps(bounded_json(value, max_items=100), indent=2, sort_keys=True, default=str))


if __name__ == '__main__':
    sys.exit(main())
