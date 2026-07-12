from __future__ import annotations

import asyncio
import json
import sys

from app.database import SessionLocal
from app.copernicus_jobs import acquire_job, ingest_job, mark_job_failed


def main() -> int:
    with SessionLocal() as db:
        job = acquire_job(db)
        if not job:
            print(json.dumps({'status': 'no_job'}))
            return 0
        job_id = job.id
        try:
            info = asyncio.run(ingest_job(db, job))
        except Exception as exc:
            mark_job_failed(db, job, exc)
            print(json.dumps({'status': 'failed', 'job_id': job_id, 'error': str(exc)[:500]}))
            return 4
        print(json.dumps({'status': 'succeeded', 'job_id': job_id, **info}, default=str))
        return 0


if __name__ == '__main__':
    sys.exit(main())
