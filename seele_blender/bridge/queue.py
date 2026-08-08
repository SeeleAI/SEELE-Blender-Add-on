import threading

from .. import runtime
from ..errors import CancelledError, SeeleError
from ..transfer.client import consume_transfer
from ..transfer.downloader import download_manifest
from ..transfer.manifest import (
    DCC_PROTOCOL,
    LEGACY_PROTOCOL,
    legacy_to_dcc,
    validate_direct_envelope,
    validate_gltf_dependencies,
    validate_legacy_envelope,
)


def receive(payload, origin):
    config = runtime.CONFIG
    if not isinstance(payload, dict):
        raise SeeleError("INVALID_REQUEST", "Transfer request must be an object")
    if payload.get("version") == DCC_PROTOCOL:
        manifest = validate_direct_envelope(
            payload,
            config.receiver_id,
            origin,
            runtime.CHALLENGES.consume,
            config.formats,
            config.download_hosts,
        )
        transfer_id = manifest["transferId"]
        runtime.STATE.create(transfer_id, DCC_PROTOCOL, manifest=manifest)
        runtime.STATE.update(transfer_id, warnings=list(manifest.get("integrityWarnings", [])))
        target = _prepare_download
    elif payload.get("protocol") == LEGACY_PROTOCOL:
        if not config.legacy_enabled:
            raise SeeleError("PROTOCOL_UNSUPPORTED", "Legacy consume protocol is disabled", 409)
        envelope = validate_legacy_envelope(payload, config.receiver_id, origin, runtime.CHALLENGES.consume)
        transfer_id = envelope["transferId"]
        runtime.STATE.create(transfer_id, LEGACY_PROTOCOL, legacy_envelope=envelope)
        target = _prepare_legacy
    else:
        raise SeeleError("PROTOCOL_UNSUPPORTED", "Transfer protocol is unsupported", 409)
    accepted = runtime.STATE.get(transfer_id)
    thread = threading.Thread(target=_run_worker, args=(target, transfer_id), name="SEELE-Transfer", daemon=True)
    runtime.track_worker(thread)
    thread.start()
    return accepted


def _run_worker(target, transfer_id):
    try:
        target(transfer_id)
    finally:
        runtime.untrack_worker(threading.current_thread())


def _prepare_legacy(transfer_id):
    config = runtime.CONFIG
    try:
        item = runtime.STATE.get(transfer_id, internal=True)
        raw_manifest = consume_transfer(config.legacy_consume_url, item["legacyEnvelope"])
        if not isinstance(raw_manifest, dict):
            raise SeeleError("INVALID_MANIFEST", "Legacy authorization response is invalid")
        if raw_manifest.get("transferId") != transfer_id:
            raise SeeleError("INVALID_MANIFEST", "Legacy manifest transfer id does not match")
        manifest = legacy_to_dcc(raw_manifest, config.receiver_id, config.formats, config.download_hosts)
        existing_warnings = runtime.STATE.get(transfer_id).get("warnings", [])
        runtime.STATE.update(
            transfer_id,
            manifest=manifest,
            warnings=existing_warnings + list(manifest.get("integrityWarnings", [])) + ["Legacy consume protocol is deprecated and will be removed in 0.3.0"],
        )
        _download(transfer_id)
    except Exception as exc:
        _handle_failure(transfer_id, exc)


def _prepare_download(transfer_id):
    try:
        _download(transfer_id)
    except Exception as exc:
        _handle_failure(transfer_id, exc)


def _download(transfer_id):
    config = runtime.CONFIG
    item = runtime.STATE.get(transfer_id, internal=True)
    manifest = item["manifest"]
    runtime.STATE.update(
        transfer_id,
        state="downloading",
        stage="downloading",
        progress=5,
        expected="accepted",
        displayName=str(manifest.get("displayName") or manifest["entryFilePath"]),
    )

    def cancelled():
        return runtime.STATE.is_cancelled(transfer_id)

    def progress(done, total):
        if not cancelled():
            percentage = 5 + int((done / total) * 70) if total else 75
            runtime.STATE.update(transfer_id, progress=percentage, expected="downloading")

    local_files = download_manifest(
        manifest,
        config.cache_dir,
        item["instanceId"],
        config.download_hosts,
        cancelled,
        progress,
    )
    if cancelled():
        raise CancelledError("downloading")
    runtime.STATE.update(transfer_id, state="verifying", stage="verifying", progress=80, expected="downloading")
    validate_gltf_dependencies(manifest, local_files)
    runtime.STATE.update(
        transfer_id,
        state="queued",
        stage="queued",
        progress=85,
        expected="verifying",
        localFiles=local_files,
    )
    runtime.IMPORT_QUEUE.put(transfer_id)


def _handle_failure(transfer_id, exc):
    try:
        current = runtime.STATE.get(transfer_id)
        if isinstance(exc, CancelledError) or current["state"] == "cancelled":
            if current["state"] not in {"cancelled", "failed"}:
                runtime.STATE.request_cancel(transfer_id)
            return
        runtime.STATE.fail(transfer_id, exc)
    except SeeleError:
        pass


def retry_import(transfer_id):
    runtime.STATE.begin_import_retry(transfer_id)
    runtime.IMPORT_QUEUE.put(transfer_id)
