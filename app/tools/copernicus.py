from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.database import SessionLocal
from app.copernicus import DEFAULT_DATASET_ID, DEFAULT_PRODUCT_ID, REQUIRED_VARIABLE_MAP, load_copernicus_config
from app.copernicus_jobs import (
    acquire_job,
    detect_publication,
    enqueue_latest,
    ingest_job,
    latest_status,
    mark_job_failed,
    record_waiting,
    run_toolbox_describe,
)


def _print(obj):
    print(json.dumps(obj, indent=2, sort_keys=True, default=str))


def verify_auth(_args):
    cfg = load_copernicus_config()
    missing = [m for m in cfg.missing_reasons if 'USERNAME' not in m and 'PASSWORD' not in m]
    if not cfg.username or not cfg.password:
        _print({'ok': False, 'status': 'authentication_failed', 'reason': 'Copernicus credentials are not configured'})
        return 2
    if missing:
        _print({'ok': False, 'status': 'degraded', 'reasons': missing})
        return 2
    # describe is the lightest official-toolbox auth/catalog check available here.
    run_toolbox_describe()
    _print({'ok': True, 'status': 'authenticated', 'product_id': cfg.product_id, 'dataset_id': cfg.dataset_id})
    return 0


def inspect(_args):
    metadata = run_toolbox_describe()
    probe = detect_publication()
    _print({
        'ok': not probe.missing_core_variables,
        'product_id': DEFAULT_PRODUCT_ID,
        'dataset_id': DEFAULT_DATASET_ID,
        'variables': REQUIRED_VARIABLE_MAP,
        'publication_identity': probe.publication_identity,
        'latest_available_forecast_time': probe.latest_available_forecast_time,
        'missing_variables': probe.missing_variables,
        'metadata_checked': bool(metadata),
    })
    return 0 if not probe.missing_core_variables else 3


def check(_args):
    with SessionLocal() as db:
        try:
            result, job_id = enqueue_latest(db)
        except Exception as exc:
            record_waiting(db, 'waiting_for_publication', str(exc))
            _print({'status': 'waiting_for_publication', 'reason': str(exc)[:500]})
            return 0
        _print({'status': result, 'job_id': job_id})
        return 0 if result != 'schema_degraded' else 3


def reconcile(_args):
    return check(_args)


def enqueue_latest_cmd(_args):
    with SessionLocal() as db:
        result, job_id = enqueue_latest(db)
        _print({'status': result, 'job_id': job_id})
        return 0 if result != 'schema_degraded' else 3


def ingest_latest(_args):
    with SessionLocal() as db:
        result, job_id = enqueue_latest(db)
        if result in ('already_imported', 'schema_degraded'):
            _print({'status': result, 'job_id': job_id})
            return 0 if result == 'already_imported' else 3
        job = acquire_job(db)
        if not job:
            _print({'status': 'no_job'})
            return 0
        try:
            info = asyncio.run(ingest_job(db, job))
        except Exception as exc:
            mark_job_failed(db, job, exc)
            _print({'status': 'failed', 'error': str(exc)[:500]})
            return 4
        _print({'status': 'succeeded', **info})
        return 0


def status(_args):
    with SessionLocal() as db:
        _print(latest_status(db))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='WaveWatch Copernicus Marine operations')
    sub = parser.add_subparsers(dest='command', required=True)
    commands = {
        'verify-auth': verify_auth,
        'inspect': inspect,
        'check': check,
        'reconcile': reconcile,
        'enqueue-latest': enqueue_latest_cmd,
        'ingest-latest': ingest_latest,
        'status': status,
    }
    for name, func in commands.items():
        p = sub.add_parser(name)
        p.set_defaults(func=func)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
