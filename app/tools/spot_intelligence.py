from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Sequence

from ..database import SessionLocal
from ..repositories.spot_assessment_repository import (
    count_spot_assessment_points_for_run, count_spot_assessment_runs,
    get_spot_assessment_point, get_spot_assessment_run,
    latest_spot_assessment_runs, list_spot_assessment_points_for_run,
)
from ..services.consensus_safety import bounded_json, redact_text
from ..services.spot_intelligence_engine import calculate_spot_assessment

RUN_SUMMARY_MAX_BYTES = 16_384
CLI_JSON_MAX_BYTES = 1_650_000


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError('must be a positive integer')
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError('must be a nonnegative integer')
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='python -m app.tools.spot_intelligence')
    sub = parser.add_subparsers(dest='command', required=True)
    calculate = sub.add_parser('calculate')
    calculate.add_argument('--consensus-run-id', required=True, type=_positive_int)
    calculate.add_argument('--spot-id', action='append', type=_positive_int)
    calculate.add_argument('--force', action='store_true')
    calculate.add_argument('--dry-run', action='store_true')
    status = sub.add_parser('status')
    status.add_argument('--limit', type=_positive_int, default=10)
    status.add_argument('--offset', type=_nonnegative_int, default=0)
    inspect = sub.add_parser('inspect-run')
    inspect.add_argument('run_id', type=_positive_int)
    inspect.add_argument('--limit', type=_positive_int, default=50)
    inspect.add_argument('--offset', type=_nonnegative_int, default=0)
    explain = sub.add_parser('explain-point')
    explain.add_argument('point_id', type=_positive_int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    db = SessionLocal()
    try:
        if args.command == 'status':
            rows = []
            page_limit = min(args.limit, 100)
            total = count_spot_assessment_runs(db)
            for run in latest_spot_assessment_runs(db, limit=page_limit, offset=args.offset):
                summary = _run_summary(run)
                summary['point_count'] = count_spot_assessment_points_for_run(db, run.id)
                rows.append(summary)
            has_more = args.offset + len(rows) < total
            _print_json({
                'total_run_count': total, 'returned_run_count': len(rows),
                'offset': args.offset, 'limit': page_limit, 'truncated': has_more,
                'next_offset': args.offset + len(rows) if has_more else None,
                'runs': rows,
            })
            return 0
        if args.command == 'inspect-run':
            run = get_spot_assessment_run(db, args.run_id)
            if run is None:
                _print_json({'error': 'spot_assessment_run_not_found', 'run_id': args.run_id})
                return 2
            total = count_spot_assessment_points_for_run(db, run.id)
            page_limit = min(args.limit, 100)
            points = list_spot_assessment_points_for_run(db, run.id, limit=page_limit, offset=args.offset)
            has_more = args.offset + len(points) < total
            _print_json({
                'run': _run_summary(run), 'total_point_count': total,
                'point_count': total, 'returned_point_count': len(points),
                'offset': args.offset, 'limit': page_limit, 'truncated': has_more,
                'next_offset': args.offset + len(points) if has_more else None,
                'points': [_point_summary(point) for point in points],
            })
            return 0
        if args.command == 'explain-point':
            point = get_spot_assessment_point(db, args.point_id)
            if point is None:
                _print_json({'error': 'spot_assessment_point_not_found', 'point_id': args.point_id})
                return 2
            run = get_spot_assessment_run(db, point.assessment_run_id)
            _print_json({'point': _point_summary(point), 'run': _run_summary(run) if run else None, 'hazards': bounded_json(point.hazard_flags_json), 'uncertainty': bounded_json(point.uncertainty_factors_json), 'factor_details': bounded_json(point.factor_details_json, max_items=64)})
            return 0
        spot_ids = tuple(sorted(set(args.spot_id))) if args.spot_id else None
        result = calculate_spot_assessment(db, args.consensus_run_id, spot_ids=spot_ids, force=args.force, dry_run=args.dry_run)
        _print_json(asdict(result))
        return 0
    except ValueError as exc:
        _print_json({'error': 'invalid_request', 'message': redact_text(exc, max_length=300)})
        return 2
    except Exception as exc:
        _print_json({'error': 'spot_intelligence_command_failed', 'message': redact_text(exc, max_length=500)})
        return 1
    finally:
        db.close()


def _run_summary(run) -> dict:
    return bounded_json({
        'id': run.id, 'consensus_run_id': run.consensus_run_id, 'status': run.status,
        'calculated_at': run.calculated_at.isoformat(), 'spot_rules_version': run.spot_rules_version,
        'spot_rules_hash': run.spot_rules_hash, 'engine_version': run.spot_intelligence_engine_version,
        'configuration_hash': run.configuration_hash,
        'calculation_scope_hash': run.calculation_scope_hash,
        'recalculation_sequence': run.recalculation_sequence,
        'error_message': redact_text(run.error_message, max_length=1000) if run.error_message else None,
        'metadata': run.metadata_json,
    }, max_items=64, max_bytes=RUN_SUMMARY_MAX_BYTES)


def _point_summary(point) -> dict:
    return {
        'id': point.id, 'assessment_run_id': point.assessment_run_id, 'spot_id': point.spot_id,
        'valid_at': point.valid_at.isoformat(), 'swell_direction_fit': point.swell_direction_fit,
        'swell_height_fit': point.swell_height_fit, 'period_fit': point.period_fit,
        'wind_direction_fit': point.wind_direction_fit, 'wind_speed_fit': point.wind_speed_fit,
        'tide_fit': point.tide_fit, 'breaking_wave_min': point.breaking_wave_min,
        'breaking_wave_max': point.breaking_wave_max,
    }


def _print_json(value) -> None:
    print(json.dumps(bounded_json(value, max_items=100, max_bytes=CLI_JSON_MAX_BYTES), sort_keys=True, separators=(',', ':'), default=str))


if __name__ == '__main__':
    sys.exit(main())
