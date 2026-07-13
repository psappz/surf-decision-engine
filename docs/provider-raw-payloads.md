# Provider raw payloads

## Location
Small JSON provider payloads are stored under `data/provider-raw/<provider>/` as gzip JSON. Copernicus NetCDF files remain in the existing Copernicus cache/raw location and are referenced by path.

## Naming and checksums
JSON file names derive from a SHA-256 hash of provider, publication identity, and payload. Stored metadata includes checksum and content size.

## Security exclusions
No credentials, request authorization headers, cookies, or unbounded debug data are written.

## Retention and cleanup
PR 2 documents retention but does not implement final cleanup. Copernicus cleanup remains owned by the existing Copernicus raw-file policy.

## Backups
Provider raw files are operational evidence and should be included with application data backups if ledger replay is required.
