from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta

from ..database import SessionLocal
from ..repositories.consensus_repository import get_consensus_point, latest_consensus_runs, list_consensus_points_for_run
from ..services.consensus_configuration import default_consensus_configuration
from ..services.consensus_engine import ConsensusCalculationRequest, ConsensusEngine


def parse_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    dt = datetime.fromisoformat(text)
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='python -m app.tools.consensus')
    sub = parser.add_subparsers(dest='cmd', required=True)
    latest = sub.add_parser('calculate-latest')
    latest.add_argument('--hours', type=int, default=72)
    latest.add_argument('--spot-id', action='append', type=int, default=[])
    latest.add_argument('--force', action='store_true')
    latest.add_argument('--dry-run', action='store_true')

    calc = sub.add_parser('calculate')
    calc.add_argument('--cutoff', required=True)
    calc.add_argument('--valid-from', required=True)
    calc.add_argument('--valid-until', required=True)
    calc.add_argument('--spot-id', action='append', type=int, default=[])
    calc.add_argument('--force', action='store_true')
    calc.add_argument('--dry-run', action='store_true')

    sub.add_parser('status')
    inspect = sub.add_parser('inspect-run')
    inspect.add_argument('run_id', type=int)
    explain = sub.add_parser('explain-point')
    explain.add_argument('point_id', type=int)
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        if args.cmd == 'status':
            runs = latest_consensus_runs(db, 10)
            print(json.dumps([_run_summary(r) for r in runs], indent=2, default=str))
            return 0
        if args.cmd == 'inspect-run':
            points = list_consensus_points_for_run(db, args.run_id)
            print(json.dumps({'run_id': args.run_id, 'point_count': len(points), 'points': [_point_summary(p) for p in points[:50]]}, indent=2, default=str))
            return 0 if points else 2
        if args.cmd == 'explain-point':
            point = get_consensus_point(db, args.point_id)
            if not point:
                print('point not found', file=sys.stderr)
                return 2
            print(json.dumps({'point': _point_summary(point), 'calculation_details': point.calculation_details_json}, indent=2, default=str))
            return 0
        cfg = default_consensus_configuration()
        now = datetime.now(UTC)
        if args.cmd == 'calculate-latest':
            request = ConsensusCalculationRequest(
                forecast_cutoff_at=now,
                valid_from=now - timedelta(minutes=1),
                valid_until=now + timedelta(hours=args.hours),
                spot_ids=tuple(args.spot_id) or None,
                engine_version=cfg.engine_version,
                configuration=cfg,
                trigger_reason='manual_cli_latest',
                force_recalculation=args.force,
                dry_run=args.dry_run,
            )
        else:
            request = ConsensusCalculationRequest(
                forecast_cutoff_at=parse_utc(args.cutoff),
                valid_from=parse_utc(args.valid_from),
                valid_until=parse_utc(args.valid_until),
                spot_ids=tuple(args.spot_id) or None,
                engine_version=cfg.engine_version,
                configuration=cfg,
                trigger_reason='manual_cli_historical',
                force_recalculation=args.force,
                dry_run=args.dry_run,
            )
        result = ConsensusEngine(db).calculate(request)
        print(json.dumps(result.__dict__, indent=2, default=str))
        return 0 if result.status in {'completed', 'reused', 'dry_run'} else 1
    finally:
        db.close()


def _run_summary(run):
    return {'id': run.id, 'status': run.status, 'calculated_at': run.calculated_at, 'forecast_cutoff_at': run.forecast_cutoff_at, 'engine': run.consensus_engine_version, 'configuration_hash': run.configuration_hash, 'metadata': run.metadata_json}


def _point_summary(point):
    return {'id': point.id, 'run_id': point.consensus_run_id, 'spot_id': point.spot_id, 'valid_at': point.valid_at, 'provider_count': point.provider_count, 'wave_height': point.wave_height, 'wave_direction': point.wave_direction, 'wave_period': point.wave_period, 'wind_speed': point.wind_speed, 'wind_direction': point.wind_direction, 'agreement_score': point.agreement_score, 'freshness_score': point.freshness_score, 'completeness_score': point.completeness_score, 'confidence_input_score': point.confidence_input_score}


if __name__ == '__main__':
    raise SystemExit(main())
