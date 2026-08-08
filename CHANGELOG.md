# Changelog

## 0.2.1 - 2026-08-07

- Made `sha256` and `sizeBytes` compatibility-optional: supplied values remain strict, while missing metadata produces warnings and receiver hard limits still apply.
- Split generic download failures into HTTP/expiry, TLS, timeout, network and cache-write errors.
- Fixed the Sidebar so download failures no longer expose the importer-only Retry Import action.

## 0.2.0 - 2026-08-07

- Added native `dcc-transfer.v1` direct manifest receiver.
- Added capability-based health response and actual Blender importer readiness.
- Standardized success and error envelopes, stable error codes, stages and retryability.
- Bound one-time challenges to receiver installation and exact Web Origin.
- Moved `blender-transfer.v1` Consume support behind a disabled legacy switch; removal is scheduled for 0.3.0.
- Added request limits, download concurrency limits, expiry checks, exact host/port redirect validation and disk-space checks.
- Added sentinel-protected cache cleanup and per-transfer/per-attempt directory isolation.
- Added cancel-aware Blender datablock rollback and explicit optional framing.
- Added shared contract fixtures, privacy/network documentation and troubleshooting guidance.

## 0.1.0 - 2026-08-06

- Initial Blender 4.0+ MVP with localhost Bridge and GLB/glTF, FBX and STL importers.
