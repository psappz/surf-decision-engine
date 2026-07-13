# Provider ledger failure recovery

## Failure stages
1. Source fetch failure: provider job fails as before.
2. Legacy runtime persistence failure: provider job fails.
3. Ledger persistence failure with feature flag enabled: mark `ledger_failed`, retain error metadata, and do not silently report success.

## Retry eligibility
Retries are safe when the source publication identity is unchanged. A new fetch attempt is created; previous successful runs are not overwritten.

## Duplicate handling
Publication and point uniqueness constraints reject duplicates. Failed batch insertion rolls back the batch.

## Raw payload preservation
Copernicus NetCDF references and small JSON gzip payloads preserve enough state for diagnosis. Secrets, cookies, and auth headers are not stored.

## Manual recovery
Inspect `provider_fetches.status='ledger_failed'`, fix configuration or data shape, then rerun the provider job. Do not retry if the source payload is known corrupt and no corrected provider publication exists.
