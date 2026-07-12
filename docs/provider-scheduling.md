# Provider scheduling

Copernicus `GLOBAL_ANALYSISFORECAST_WAV_001_027` publishes around the 00:00 UTC and 12:00 UTC cycles. The dataset has three-hour forecast resolution, but new source data are not published every three hours.

WaveWatch uses publication-aware scheduling:

```cron
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
CRON_TZ=UTC

*/10 0-2 * * *   deploy /opt/wavewatch/app/deploy/scripts/copernicus-cron.sh check >> /var/log/wavewatch/copernicus-cron.log 2>&1
*/10 12-14 * * * deploy /opt/wavewatch/app/deploy/scripts/copernicus-cron.sh check >> /var/log/wavewatch/copernicus-cron.log 2>&1
30 18 * * *      deploy /opt/wavewatch/app/deploy/scripts/copernicus-cron.sh reconcile >> /var/log/wavewatch/copernicus-cron.log 2>&1
```

The wrapper performs a lightweight catalogue check through the app CLI. It launches the worker only when a new publication identity is queued.

Duplicate protection:

- unique DB constraint on `(provider, dataset_id, publication_identity)`;
- job status/lease fields for active work;
- wrapper-level `flock` at `/tmp/wavewatch-copernicus-cron.lock`.

The 18:30 UTC reconciliation catches missed publication-window checks, downtime, and failed previous attempts while preserving idempotency.
