import os
import shutil
import socket
import ssl
import threading
import urllib.error
import urllib.request
from pathlib import Path

from ..errors import CancelledError, SeeleError
from .manifest import MAX_FILE_BYTES, MAX_TOTAL_BYTES, ensure_not_expired, file_sha256, is_download_url_allowed
from .paths import resolve_cache_path, transfer_dir


DOWNLOAD_SLOTS = threading.BoundedSemaphore(2)


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    max_redirections = 5
    max_repeats = 2

    def __init__(self, allowed_hosts, manifest):
        super().__init__()
        self.allowed_hosts = tuple(allowed_hosts)
        self.manifest = manifest

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        ensure_not_expired(self.manifest, "downloading")
        if not is_download_url_allowed(newurl, self.allowed_hosts):
            raise SeeleError("DOWNLOAD_HOST_BLOCKED", "Download redirect host is not allowed", 403, False, "downloading")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_manifest(manifest, cache_root, instance_id, allowed_hosts, cancelled, progress=None, timeout=60):
    while not DOWNLOAD_SLOTS.acquire(timeout=0.2):
        if cancelled():
            raise CancelledError("downloading")
        ensure_not_expired(manifest, "downloading")
    try:
        return _download_manifest(manifest, cache_root, instance_id, allowed_hosts, cancelled, progress, timeout)
    finally:
        DOWNLOAD_SLOTS.release()


def _download_manifest(manifest, cache_root, instance_id, allowed_hosts, cancelled, progress=None, timeout=60):
    ensure_not_expired(manifest, "downloading")
    root = transfer_dir(cache_root, manifest["transferId"], instance_id, create=True)
    opener = urllib.request.build_opener(
        SafeRedirectHandler(allowed_hosts, manifest),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    declared_sizes = [item["sizeBytes"] for item in manifest["files"]]
    total = sum(declared_sizes) if all(size is not None for size in declared_sizes) else 0
    max_total = manifest.get("effectiveMaxTotalBytes", MAX_TOTAL_BYTES)
    received_total = 0
    local_files = {}
    try:
        for item in manifest["files"]:
            if cancelled():
                raise CancelledError("downloading")
            ensure_not_expired(manifest, "downloading")
            target = resolve_cache_path(root, item["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            required = (item["sizeBytes"] if item["sizeBytes"] is not None else min(max_total, 64 * 1024 * 1024)) + 16 * 1024 * 1024
            if shutil.disk_usage(target.parent).free < required:
                raise SeeleError("INTERNAL_ERROR", "Insufficient disk space for transfer", 507, True, "downloading")
            temporary = Path(str(target) + ".part")
            ensure_not_expired(manifest, "downloading")
            request = urllib.request.Request(item["downloadUrl"], headers={"Accept": "*/*"})
            written = 0
            try:
                response = opener.open(request, timeout=timeout)
            except urllib.error.HTTPError as exc:
                if exc.code in {401, 403, 404, 410}:
                    raise SeeleError("DOWNLOAD_EXPIRED", "Download authorization was rejected or expired", 401, False, "downloading") from exc
                if exc.code == 429 or 500 <= exc.code <= 599:
                    raise SeeleError("DOWNLOAD_HTTP_ERROR", "Download service is temporarily unavailable", 502, True, "downloading") from exc
                raise SeeleError("DOWNLOAD_HTTP_ERROR", "Download server rejected the request", 502, False, "downloading") from exc
            except urllib.error.URLError as exc:
                reason = exc.reason
                if isinstance(reason, ssl.SSLCertVerificationError):
                    raise SeeleError("DOWNLOAD_TLS_ERROR", "Download TLS certificate verification failed", 502, False, "downloading") from exc
                if isinstance(reason, (TimeoutError, socket.timeout)):
                    raise SeeleError("DOWNLOAD_TIMEOUT", "Download connection timed out", 504, True, "downloading") from exc
                raise SeeleError("DOWNLOAD_NETWORK_ERROR", "Download server could not be reached", 502, True, "downloading") from exc
            except (TimeoutError, socket.timeout) as exc:
                raise SeeleError("DOWNLOAD_TIMEOUT", "Download connection timed out", 504, True, "downloading") from exc
            except OSError as exc:
                raise SeeleError("DOWNLOAD_NETWORK_ERROR", "Download connection failed", 502, True, "downloading") from exc
            try:
                with response:
                    ensure_not_expired(manifest, "downloading")
                    if not is_download_url_allowed(response.geturl(), allowed_hosts):
                        raise SeeleError("DOWNLOAD_HOST_BLOCKED", "Final download host is not allowed", 403, False, "downloading")
                    try:
                        output = open(temporary, "wb")
                    except OSError as exc:
                        raise SeeleError("DOWNLOAD_WRITE_FAILED", "Transfer cache file could not be created", 500, True, "downloading") from exc
                    with output:
                        while True:
                            if cancelled():
                                raise CancelledError("downloading")
                            ensure_not_expired(manifest, "downloading")
                            try:
                                chunk = response.read(1024 * 1024)
                            except (OSError, TimeoutError, socket.timeout) as exc:
                                raise SeeleError("DOWNLOAD_NETWORK_ERROR", "Download connection was interrupted", 502, True, "downloading") from exc
                            if not chunk:
                                break
                            written += len(chunk)
                            if item["sizeBytes"] is not None and written > item["sizeBytes"]:
                                raise SeeleError("DOWNLOAD_SIZE_MISMATCH", "Downloaded file size does not match manifest", 400, False, "verifying")
                            if written > MAX_FILE_BYTES or received_total + written > max_total:
                                raise SeeleError("DOWNLOAD_SIZE_MISMATCH", "Downloaded data exceeds receiver limits", 413, False, "downloading")
                            try:
                                output.write(chunk)
                            except OSError as exc:
                                raise SeeleError("DOWNLOAD_WRITE_FAILED", "Transfer cache file could not be written", 500, True, "downloading") from exc
                            if progress:
                                progress(received_total + written, total)
            except SeeleError:
                raise
            except (TimeoutError, socket.timeout) as exc:
                raise SeeleError("DOWNLOAD_TIMEOUT", "Download connection timed out", 504, True, "downloading") from exc
            except OSError as exc:
                raise SeeleError("DOWNLOAD_NETWORK_ERROR", "Download connection was interrupted", 502, True, "downloading") from exc
            if item["sizeBytes"] is not None and written != item["sizeBytes"]:
                raise SeeleError("DOWNLOAD_SIZE_MISMATCH", "Downloaded file size does not match manifest", 400, False, "verifying")
            if item["sha256"] is not None and file_sha256(temporary) != item["sha256"]:
                raise SeeleError("DOWNLOAD_HASH_MISMATCH", "Downloaded file verification failed", 400, False, "verifying")
            os.replace(temporary, target)
            local_files[item["path"]] = str(target)
            received_total += written
    except Exception:
        for part in root.rglob("*.part"):
            try:
                part.unlink()
            except OSError:
                pass
        raise
    return local_files
