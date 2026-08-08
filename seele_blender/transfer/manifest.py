import hashlib
import json
import posixpath
import re
import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

from ..errors import SeeleError
from .paths import safe_relative_path


DCC_PROTOCOL = "dcc-transfer.v1"
LEGACY_PROTOCOL = "blender-transfer.v1"
SUPPORTED_FORMATS = {"glb", "gltf", "fbx", "stl"}
MAX_FILES = 128
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_FILE_BYTES = 1024 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FILE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
KINDS = {"MODEL", "TEXTURE", "AUXILIARY"}
UNITS_TO_METERS = {"millimeter": 0.001, "mm": 0.001, "centimeter": 0.01, "cm": 0.01, "meter": 1.0, "m": 1.0}


def parse_time(value, code="TRANSFER_EXPIRED"):
    if not isinstance(value, str):
        raise SeeleError(code, "Transfer expiry is missing", 401, False, "accepted")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result
    except ValueError as exc:
        raise SeeleError("INVALID_MANIFEST", "Transfer expiry is invalid") from exc


def ensure_not_expired(manifest, stage="downloading"):
    if parse_time(manifest.get("expiresAt"), "DOWNLOAD_EXPIRED") <= datetime.now(timezone.utc):
        raise SeeleError("DOWNLOAD_EXPIRED", "Download authorization expired", 401, False, stage)


def _uuid(value, field):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError) as exc:
        raise SeeleError("INVALID_MANIFEST", f"{field} must be a UUID") from exc


def _strict_positive_int(value, field, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, int) or value < (0 if allow_zero else 1):
        raise SeeleError("INVALID_MANIFEST", f"{field} is invalid")
    return value


def url_authority(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    try:
        port = parsed.port or 443
    except ValueError:
        return None
    host = parsed.hostname.lower().rstrip(".")
    return host if port == 443 else f"{host}:{port}"


def is_download_url_allowed(url, allowed_hosts):
    if not isinstance(url, str):
        return False
    return url_authority(url) in {value.strip().lower().rstrip(".") for value in allowed_hosts if value.strip()}


def validate_direct_envelope(data, receiver_id, origin, consume_challenge, formats, allowed_hosts):
    if not isinstance(data, dict):
        raise SeeleError("INVALID_REQUEST", "JSON object required")
    if data.get("version") != DCC_PROTOCOL:
        raise SeeleError("PROTOCOL_UNSUPPORTED", "Transfer protocol is unsupported", 409)
    if data.get("receiverId") != receiver_id:
        raise SeeleError("RECEIVER_MISMATCH", "Receiver does not match", 403)
    manifest = validate_dcc_manifest(data.get("manifest"), receiver_id, formats, allowed_hosts)
    consume_challenge(data.get("challenge"), receiver_id, origin)
    return manifest


def validate_dcc_manifest(data, receiver_id, formats, allowed_hosts):
    if not isinstance(data, dict):
        raise SeeleError("INVALID_MANIFEST", "Manifest must be an object")
    if data.get("version") != DCC_PROTOCOL:
        raise SeeleError("PROTOCOL_UNSUPPORTED", "Manifest protocol is unsupported", 409)
    transfer_id = _uuid(data.get("transferId"), "transferId")
    if data.get("receiverId") != receiver_id:
        raise SeeleError("RECEIVER_MISMATCH", "Manifest receiver does not match", 403)
    target = data.get("target")
    if not isinstance(target, dict) or target.get("dcc") != "blender":
        raise SeeleError("RECEIVER_MISMATCH", "Manifest target is not Blender", 403)
    fmt = str(target.get("format", "")).lower()
    if fmt not in SUPPORTED_FORMATS or fmt not in set(formats):
        raise SeeleError("UNSUPPORTED_FORMAT", "Manifest format is unsupported", 409)
    expires = parse_time(data.get("expiresAt"))
    if expires <= datetime.now(timezone.utc):
        raise SeeleError("TRANSFER_EXPIRED", "Transfer expired", 401, False, "accepted")
    if data.get("createdAt") is not None:
        created = parse_time(data.get("createdAt"))
        if created > expires:
            raise SeeleError("INVALID_MANIFEST", "Manifest timestamps are inconsistent")

    limits = data.get("limits", {})
    if not isinstance(limits, dict):
        raise SeeleError("INVALID_MANIFEST", "Manifest limits must be an object")
    manifest_max_files = _strict_positive_int(limits.get("maxFiles", MAX_FILES), "limits.maxFiles")
    manifest_max_total = _strict_positive_int(limits.get("maxTotalBytes", MAX_TOTAL_BYTES), "limits.maxTotalBytes")
    max_files = min(manifest_max_files, MAX_FILES)
    max_total = min(manifest_max_total, MAX_TOTAL_BYTES)
    files = data.get("files")
    if not isinstance(files, list) or not files:
        raise SeeleError("INVALID_MANIFEST", "Manifest files must be a non-empty array")
    if len(files) > max_files:
        raise SeeleError("INVALID_MANIFEST", "Manifest exceeds the file count limit", 413)

    ids = set()
    paths = set()
    total = 0
    normalized_files = []
    for item in files:
        if not isinstance(item, dict):
            raise SeeleError("INVALID_MANIFEST", "Manifest file entry is invalid")
        file_id = item.get("id")
        if not isinstance(file_id, str) or not FILE_ID_RE.fullmatch(file_id) or file_id in ids:
            raise SeeleError("INVALID_MANIFEST", "Manifest file id is invalid or duplicated")
        ids.add(file_id)
        rel = safe_relative_path(item.get("path"))
        path_key = rel.as_posix().casefold()
        if path_key in paths:
            raise SeeleError("INVALID_MANIFEST", "Manifest file path is duplicated")
        paths.add(path_key)
        kind = item.get("kind")
        if kind not in KINDS:
            raise SeeleError("INVALID_MANIFEST", "Manifest file kind is invalid")
        file_format = str(item.get("format", "")).lower()
        if kind == "MODEL" and file_format not in SUPPORTED_FORMATS:
            raise SeeleError("INVALID_MANIFEST", "Model file format is invalid")
        size = item.get("sizeBytes")
        if size is not None:
            size = _strict_positive_int(size, "files[].sizeBytes", allow_zero=True)
            if size > MAX_FILE_BYTES:
                raise SeeleError("INVALID_MANIFEST", "Manifest file exceeds the size limit", 413)
            total += size
            if total > max_total:
                raise SeeleError("INVALID_MANIFEST", "Manifest exceeds the total size limit", 413)
        digest = item.get("sha256")
        if digest is not None and (not isinstance(digest, str) or not SHA256_RE.fullmatch(digest)):
            raise SeeleError("INVALID_MANIFEST", "Manifest SHA-256 is invalid")
        download_url = item.get("downloadUrl")
        if not is_download_url_allowed(download_url, allowed_hosts):
            raise SeeleError("DOWNLOAD_HOST_BLOCKED", "Download host is not allowed", 403, False, "downloading")
        entry = dict(item)
        entry.update({"path": rel.as_posix(), "format": file_format, "sizeBytes": size, "sha256": digest})
        normalized_files.append(entry)

    entry_id = data.get("entryFileId")
    entry = next((item for item in normalized_files if item["id"] == entry_id), None)
    if entry is None:
        raise SeeleError("DEPENDENCY_MISSING", "Manifest entry file is missing")
    if entry["kind"] != "MODEL" or entry["format"] != fmt:
        raise SeeleError("INVALID_MANIFEST", "Entry file does not match target format")
    if PurePosixPath(entry["path"]).suffix.lower() != f".{fmt}":
        raise SeeleError("INVALID_MANIFEST", "Entry file extension does not match target format")
    unit_scale = data.get("unitScaleMeters")
    if unit_scale is not None:
        if isinstance(unit_scale, bool) or not isinstance(unit_scale, (int, float)) or unit_scale <= 0:
            raise SeeleError("INVALID_MANIFEST", "unitScaleMeters is invalid")
    if fmt == "stl" and unit_scale is None:
        raise SeeleError("DEPENDENCY_MISSING", "STL requires unitScaleMeters")
    materials = data.get("materials", [])
    if not isinstance(materials, list):
        raise SeeleError("INVALID_MANIFEST", "Manifest materials must be an array")

    missing_hash = sum(1 for item in normalized_files if item["sha256"] is None)
    missing_size = sum(1 for item in normalized_files if item["sizeBytes"] is None)
    integrity_warnings = []
    if missing_hash:
        integrity_warnings.append(f"{missing_hash} file(s) have no SHA-256; content integrity could not be verified")
    if missing_size:
        integrity_warnings.append(f"{missing_size} file(s) have no declared size; hard receiver limits were applied")
    result = dict(data)
    result.update({
        "transferId": transfer_id,
        "format": fmt,
        "entryFilePath": entry["path"],
        "files": normalized_files,
        "materials": materials,
        "integrityWarnings": integrity_warnings,
        "effectiveMaxTotalBytes": max_total,
    })
    return result


def validate_gltf_dependencies(manifest, local_files):
    if manifest["format"] != "gltf":
        return
    entry_path = manifest["entryFilePath"]
    try:
        with open(local_files[entry_path], "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SeeleError("DEPENDENCY_MISSING", "glTF entry file cannot be inspected", 400, False, "verifying") from exc
    declared = {item["path"].casefold() for item in manifest["files"]}
    base = str(PurePosixPath(entry_path).parent)
    for section in ("buffers", "images"):
        values = document.get(section, [])
        if not isinstance(values, list):
            raise SeeleError("INVALID_MANIFEST", "glTF dependency section is invalid")
        for item in values:
            uri = item.get("uri") if isinstance(item, dict) else None
            if not uri or uri.startswith("data:"):
                continue
            decoded = unquote(uri)
            if decoded != uri or urlparse(uri).scheme or "?" in uri or "#" in uri:
                raise SeeleError("DEPENDENCY_MISSING", "glTF dependency URI is unsafe")
            combined = posixpath.normpath(posixpath.join(base, uri))
            safe_relative_path(combined)
            if combined.casefold() not in declared:
                raise SeeleError("DEPENDENCY_MISSING", "glTF dependency is absent from manifest")


def validate_legacy_envelope(data, receiver_id, origin, consume_challenge):
    if not isinstance(data, dict) or data.get("protocol") != LEGACY_PROTOCOL:
        raise SeeleError("PROTOCOL_UNSUPPORTED", "Legacy transfer protocol is unsupported", 409)
    if data.get("receiverId") != receiver_id:
        raise SeeleError("RECEIVER_MISMATCH", "Receiver does not match", 403)
    if parse_time(data.get("expiresAt")) <= datetime.now(timezone.utc):
        raise SeeleError("TRANSFER_EXPIRED", "Transfer expired", 401)
    _uuid(data.get("transferId"), "transferId")
    token = data.get("transferToken")
    if not isinstance(token, str) or not token or len(token) > 4096:
        raise SeeleError("INVALID_REQUEST", "Legacy transfer token is invalid")
    consume_challenge(data.get("challenge"), receiver_id, origin)
    return dict(data)


def legacy_to_dcc(data, receiver_id, formats, allowed_hosts):
    if not isinstance(data, dict) or data.get("protocol") != LEGACY_PROTOCOL:
        raise SeeleError("INVALID_MANIFEST", "Legacy manifest is invalid")
    fmt = str(data.get("format", "")).lower()
    entry_path = data.get("entryFile")
    files = []
    entry_id = None
    for index, item in enumerate(data.get("files", [])):
        path = item.get("path") if isinstance(item, dict) else None
        file_id = "model" if path == entry_path else f"file_{index}"
        if path == entry_path:
            entry_id = file_id
        legacy_digest = item.get("sha256")
        files.append({
            "id": file_id,
            "kind": "MODEL" if path == entry_path else "AUXILIARY",
            "format": fmt if path == entry_path else "",
            "path": path,
            "downloadUrl": item.get("url"),
            "contentType": item.get("mimeType", "application/octet-stream"),
            "sha256": legacy_digest.lower() if isinstance(legacy_digest, str) else legacy_digest,
            "sizeBytes": item.get("size"),
        })
    unit = data.get("metersPerUnit")
    if unit is None:
        unit = UNITS_TO_METERS.get(str(data.get("sourceUnit", "")).lower())
    mapped = {
        "version": DCC_PROTOCOL,
        "transferId": data.get("transferId"),
        "target": {"dcc": "blender", "format": fmt},
        "receiverId": receiver_id,
        "displayName": data.get("displayName", "Asset"),
        "entryFileId": entry_id,
        "coordinateSystem": data.get("upAxis", "Y"),
        "unitScaleMeters": unit,
        "files": files,
        "materials": [],
        "limits": data.get("limits", {}),
        "createdAt": data.get("createdAt"),
        "expiresAt": data.get("expiresAt"),
    }
    return validate_dcc_manifest(mapped, receiver_id, formats, allowed_hosts)


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
