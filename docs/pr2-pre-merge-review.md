# PR 2 pre-merge review

## 1. PR metadata

- Repository: `psappz/surf-decision-engine`
- Product: Surf Decision Engine
- PR: #2, `feat: migrate provider ingestion to append-only ledger writes`
- URL: <https://github.com/psappz/surf-decision-engine/pull/2>
- Base: `develop`
- Head: `feature/provider-engine-ledger-migration`
- Reviewed starting commit: `9682ee5cf82bfa17a06f756e1b9090db1fddf654`
- PR state at review start: open, non-draft, mergeable

## 2. Files reviewed

Critical code paths reviewed:

- `app/config.py`
- `app/forecast_service.py`
- `app/copernicus.py`
- `app/copernicus_jobs.py`
- `app/services/provider_ledger_writer.py`
- `app/services/provider_publication_identity.py`
- `app/forecast_ledger_models.py`
- `tests/test_provider_ledger_writer.py`
- `tests/test_copernicus.py`
- `tests/test_copernicus_jobs.py`
- PR documentation under `docs/provider-*.md` and `docs/pr2-implementation-review.md`

Repository/PR commands run:

```bash
git status --short --branch
git remote -v
git fetch origin --prune
gh pr view 2 --repo psappz/surf-decision-engine --json number,title,url,state,baseRefName,headRefName,mergeable,isDraft,commits,files
gh pr diff 2 --repo psappz/surf-decision-engine --name-only
git diff --stat develop...feature/provider-engine-ledger-migration
```

## 3. Feature-flag result

Result: pass.

- `PROVIDER_LEDGER_WRITES_ENABLED` defaults to disabled in `.env.example`, `app/config.py`, and `ledger_writes_enabled()`.
- Missing environment variable means disabled.
- Only literal lowercase-normalized `true` enables writes; false-like and missing values remain disabled.
- No production compose/deployment file in the PR silently enables the flag.
- Runtime reads, recommendations, scoring, scheduler ownership, and UI paths remain on current runtime tables.
- Disabled full-suite run passed with zero ledger rows generated in the compatibility smoke database.

## 4. Provider Ledger Writer result

Result: pass after review corrections.

Verified:

- Publication resolution uses provider, dataset, and deterministic publication identity.
- Fetch attempts increment per publication and are protected by the `provider_fetches` uniqueness constraint plus retry loop.
- Forecast run rows include normalizer version and normalizer configuration hash.
- Points are inserted with `add_all()` in one nested transaction, not committed per point.
- Duplicate points inside one run trigger a rollback.
- Previous successful runs and points are not updated or deleted by the writer.
- There is no mutable global ledger context.
- Transaction ownership remains with the caller; the writer uses a nested transaction and does not commit the outer transaction.

Correction made during review:

- Hardened small JSON raw-payload persistence with sanitized provider directories, temporary gzip write plus rename, owner-only temp-file permissions, and collision detection.

## 5. Transaction-ordering result

Result: pass with noted follow-up.

Implemented order:

### Open-Meteo fixture-style bundle

```text
rate-limit check
→ normalize generated marine/weather/tide fixture values
→ legacy runtime MarineForecast/WeatherForecast/TideForecast rows staged
→ provider ledger marine write, if flag enabled
→ provider ledger weather write, if flag enabled
→ provider fetch metadata update
→ commit
→ recommendation recalculation
```

### Copernicus background job

```text
publication-aware job acquisition
→ NetCDF fetch
→ validate
→ checksum and raw file rename
→ normalize per spot/time
→ legacy runtime MarineForecast rows staged
→ Copernicus publication/fetch/job metadata staged
→ provider ledger write, if flag enabled
→ job success update
→ recommendation recalculation
→ commit
→ raw-file cleanup
```

Required properties checked:

- Ledger failures are not silently reported as complete success; failures call `mark_ledger_failure()` and raise.
- Previous committed runtime data remain available after ledger failure.
- No recommendation or UI read path depends on ledger data.
- Web requests read stored rows; provider fetches are guarded by scheduled/background or startup/provider-bundle paths, not normal page render queries.
- Retries append new fetch attempts and do not overwrite previous successful ledger points.

Follow-up risk:

- The partial-success marker is staged in the same SQLAlchemy session as the failing ingest path. The implementation raises after marking failure, so final persistence depends on caller-level exception handling. This is acceptable for PR 2 because the failure is not hidden and existing committed runtime data remain available, but a later operations hardening pass should add an explicit durable partial-failure audit path if product operations require post-failure inspection without rerun context.

## 6. Publication-identity result per provider

Result: pass after review correction.

### Copernicus Marine

- Uses product ID, dataset ID, model cycle, latest valid forecast timestamp, and catalogue metadata fingerprint.
- Correction made: the returned identity now includes the catalogue metadata fingerprint even when `latest_valid_at` exists.
- `fetched_at` is excluded.
- Identity length remains below the 500-character database column limit in regression coverage.

### Open-Meteo Marine

- Uses provider name, request geography, temporal range, issue/update metadata when available, otherwise a bounded content hash.
- Marine provider name is distinct from weather.
- Fallback hash is deterministic and bounded.

### Open-Meteo Weather

- Uses the same deterministic strategy as Marine but with provider identity `open-meteo-weather`.
- Weather and Marine cannot collide for identical coordinates/timestamps because provider name is included in the canonical identity payload.

### IPMA

- Identity builder is isolated from active ingestion.
- Identity includes feed type, endpoint, `dataUpdate`, forecast date, location ID, and category.
- No fake hourly expansion is implemented.

## 7. Copernicus mapping result

Result: pass after review correction.

Verified exact identifiers:

- Product: `GLOBAL_ANALYSISFORECAST_WAV_001_027`
- Dataset: `cmems_mod_glo_wav_anfc_0.083deg_PT3H-i`

Verified exact mapping:

| Native | Ledger/runtime field |
| --- | --- |
| `VHM0` | `wave_height` |
| `VMDR` | `wave_direction` |
| `VTPK` | `wave_period` |
| `VHM0_SW1` | `swell_wave_height` |
| `VMDR_SW1` | `swell_wave_direction` |
| `VTM01_SW1` | `swell_wave_period` |
| `VHM0_WW` | `wind_wave_height` |
| `VMDR_WW` | `wind_wave_direction` |
| `VTM01_WW` | `wind_wave_period` |

Corrections made:

- `parse_copernicus_netcdf()` now preserves requested latitude/longitude and selected Copernicus grid latitude/longitude in normalized values.
- `selected_grid` is persisted so the ledger `sample_point_id` can preserve the selected grid point.
- Regression coverage asserts requested and selected coordinates are retained.

Other checks:

- Valid times are parsed as UTC.
- Multiple valid times are retained.
- The same `valid_at` can exist in different forecast runs because point uniqueness is scoped to forecast run.
- NetCDF content is stored as filesystem path, checksum, and size metadata; NetCDF binary content is not stored in PostgreSQL.
- Scheduler, worker, and lease behavior remain unchanged.

## 8. Open-Meteo Marine result

Result: pass.

Verified mappings:

- `wave_height` → `wave_height`
- `wave_direction` → `wave_direction`
- `wave_period` → `wave_period`
- `swell_wave_height` → `swell_wave_height`
- `swell_wave_direction` → `swell_wave_direction`
- `swell_wave_period` → `swell_wave_period`
- `wind_wave_height` → `wind_wave_height`
- `wind_wave_direction` → `wind_wave_direction`
- `wind_wave_period` → `wind_wave_period`
- `sea_surface_temperature` → `water_temperature`
- `ocean_current_velocity` → `current_speed`
- `ocean_current_direction` → `current_direction`

Runtime write behavior remains unchanged; ledger writes are additional and flag-gated.

## 9. Open-Meteo Weather result

Result: pass.

Verified mappings:

- `wind_speed_10m` → `wind_speed`
- `wind_direction_10m` → `wind_direction`
- `wind_gusts_10m` → `wind_gust`

Weather-native values remain in `raw_values_json`. Missing gusts are nullable through the model. Marine and Weather use separate provider identities and separate forecast runs. Runtime weather rows remain unchanged.

## 10. IPMA result

Result: pass.

- IPMA remains disabled by product decision.
- PR 2 does not silently enable IPMA.
- No IPMA requests are performed.
- No fake hourly points are created.
- Daily ranges are not mapped to exact hourly values.
- `wavePeriodMax` is documented as an IPMA daily range field, not as peak period.
- Deterministic identity support is isolated and tested.

## 11. Raw-payload security result

Result: pass after review correction.

Checked likely secret-bearing terms in changed code and docs. Actual persisted PR 2 payload metadata excludes credentials, full headers, cookies, bearer tokens, private keys, `.env` content, and session tokens.

Corrections made:

- JSON raw-payload provider directory names are sanitized to prevent path traversal.
- JSON gzip writes use a temporary file and rename.
- Temp files are written with owner-only permissions.
- Existing files are not overwritten with different content under the same content-derived hash.

Copernicus NetCDF payloads remain filesystem files with path, checksum, size, and validation metadata; content is not stored in the database.

## 12. Idempotency and concurrency result

Result: pass with noted follow-up.

Verified by tests and schema review:

- Same publication identity reuses one publication.
- Fetch attempts increment per publication.
- Changed normalizer version/configuration produces distinguishable runs.
- Duplicate points inside one run are rejected and roll back the point batch.
- Different runs may contain the same spot/sample/valid time because uniqueness is scoped by `forecast_run_id`.
- Historical point values have no update path in the writer.

Concurrency notes:

- Fetch attempt allocation uses select-max-plus-one with a uniqueness constraint and retry loop. Database constraints catch races; PostgreSQL should handle this better than SQLite, but concurrent writer stress testing was not added in this PR.
- SQLite nullable uniqueness is avoided for `sample_point_id` because the point model stores `''` rather than `NULL`.

## 13. Runtime compatibility result

Result: pass.

Evidence:

- Full test suite passed with ledger disabled.
- Full test suite passed with ledger enabled.
- Compatibility smoke showed runtime table counts unchanged between disabled/enabled runs: 546 marine rows, 546 weather rows, 546 tide rows.
- Enabled compatibility smoke also produced 2 ledger publications, 2 forecast runs, and 1092 provider forecast points.
- `/health`, `/login`, `/surf`, `/adm`, `/mod`, and `/surf/spots/arrifana` all returned successful responses in local smoke.

## 14. Documentation result

Result: pass after corrections.

Reviewed required documents:

- `docs/provider-ledger-migration-audit.md`
- `docs/provider-ledger-writes.md`
- `docs/provider-publication-identities.md`
- `docs/provider-dual-write-operations.md`
- `docs/provider-data-mapping.md`
- `docs/provider-ledger-failure-recovery.md`
- `docs/provider-raw-payloads.md`
- `docs/pr2-implementation-review.md`

Corrections made:

- Copernicus identity documentation now matches the implemented catalogue-fingerprint identity format.
- Raw-payload documentation now reflects sanitized directories and atomic temp-file writes.
- One remaining former product prose string in Copernicus config validation was changed to Surf Decision Engine. Technical identifiers such as `wavewatch.db` and `/opt/wavewatch` remain where they are actual repository/runtime identifiers.

## 15. Test results

Commands and results:

```bash
DATABASE_URL=sqlite:////tmp/sde-pr2-review-writer.db \
.venv/bin/pytest tests/test_provider_ledger_writer.py -q
# 4 passed before corrections
```

```bash
DATABASE_URL=sqlite:////tmp/sde-pr2-review-writer2.db \
.venv/bin/pytest tests/test_provider_ledger_writer.py -q
# 6 passed after corrections
```

```bash
DATABASE_URL=sqlite:////tmp/sde-pr2-review-copernicus.db \
.venv/bin/pytest tests/test_copernicus.py -q
# 6 passed
```

```bash
DATABASE_URL=sqlite:////tmp/sde-pr2-review-bundle.db \
.venv/bin/pytest \
  tests/test_forecast_ledger.py \
  tests/test_provider_ledger_writer.py \
  tests/test_copernicus.py \
  tests/test_copernicus_jobs.py \
  -q
# 29 passed
```

```bash
PROVIDER_LEDGER_WRITES_ENABLED=true \
DATABASE_URL=sqlite:////tmp/sde-pr2-review-focused-enabled.db \
.venv/bin/pytest \
  tests/test_app.py::test_provider_failure_fallback_and_daypart_recommendations \
  tests/test_app.py::test_provider_bundle_rate_limit \
  -q
# 2 passed
```

```bash
PROVIDER_LEDGER_WRITES_ENABLED=false \
DATABASE_URL=sqlite:////tmp/sde-pr2-review-disabled.db \
.venv/bin/pytest -q
# 59 passed
```

```bash
PROVIDER_LEDGER_WRITES_ENABLED=true \
DATABASE_URL=sqlite:////tmp/sde-pr2-review-enabled.db \
.venv/bin/pytest -q
# 59 passed
```

```bash
DATABASE_URL=sqlite:////tmp/sde-pr2-smoke.db \
PROVIDER_LEDGER_WRITES_ENABLED=false \
.venv/bin/python <local TestClient smoke>
# /health 200
# /login 200
# POST /login 303
# /surf 200
# /adm 200
# /mod 200
# /surf/spots/arrifana 200
```

Warnings observed were existing deprecation warnings from `pytest_asyncio`, FastAPI `on_event`, Passlib `crypt`, and Starlette template response parameter order.

## 16. Defects found

1. Copernicus publication identity documentation and implementation did not include the catalogue metadata fingerprint in the returned identity when `latest_valid_at` existed.
2. Copernicus normalized points did not preserve requested coordinates and selected grid coordinates for the ledger sample point.
3. JSON raw-payload writing did not sanitize provider directory names and wrote gzip files directly instead of via temporary file plus rename.
4. A Copernicus config validation message still used former product prose (`WaveWatch`) rather than Surf Decision Engine.

## 17. Corrections made

- Updated Copernicus identity builder to include the metadata fingerprint in the identity string and added a regression test.
- Updated Copernicus NetCDF parsing to preserve requested latitude/longitude, selected grid latitude/longitude, and `selected_grid`; added regression coverage.
- Hardened JSON raw-payload writes with provider-name sanitization, temp gzip write plus rename, owner-only temp permissions, and collision check; added regression coverage.
- Updated docs for identity and raw payload behavior.
- Replaced former product prose in Copernicus config validation with Surf Decision Engine.

## 18. Remaining risks

- No PostgreSQL concurrent dual-writer stress test was added; concurrency safety relies on database uniqueness constraints and retry for fetch attempt allocation.
- Partial ledger-failure markers are staged in the same session and may be superseded by caller-level failure handling. The failure is not hidden, and previous committed runtime data remain intact, but a future operations hardening pass should make partial-success audit records durable independent of the failing ingest transaction if needed.
- Open-Meteo live issue/update metadata remains unavailable in the current implementation; fallback identities use request scope plus metadata/content hash as documented.

## 19. Merge recommendation

READY TO MERGE WITH NOTED FOLLOW-UP

PR 2 is within scope after the corrections above. It preserves runtime behavior, keeps ledger writes feature-flagged and disabled by default, adds deterministic provider publication identity support, preserves Copernicus sample-point information, avoids raw-payload path/security issues, and passes focused plus full regression tests with the flag both disabled and enabled.

Do not deploy from this review. Do not merge until normal project review/approval is complete.
