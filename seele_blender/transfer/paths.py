import os
import re
import shutil
import uuid
from pathlib import Path, PurePosixPath

from ..errors import SeeleError


SENTINEL = ".seele-blender-cache"
SENTINEL_CONTENT = "SEELE Blender managed cache v1\n"
_DRIVE = re.compile(r"^[A-Za-z]:")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_relative_path(value):
    if not isinstance(value, str) or not value or _CONTROL.search(value):
        raise SeeleError("INVALID_MANIFEST", "Manifest contains an unsafe file path")
    if "\\" in value or "%" in value or ":" in value:
        raise SeeleError("INVALID_MANIFEST", "Manifest file path is not canonical")
    path = PurePosixPath(value)
    if path.as_posix() != value or path.is_absolute() or _DRIVE.match(value) or any(part in ("", ".", "..") for part in path.parts):
        raise SeeleError("INVALID_MANIFEST", "Manifest contains an unsafe file path")
    if any(part.rstrip(" .").split(".")[0].upper() in _WINDOWS_RESERVED or part.endswith((" ", ".")) for part in path.parts):
        raise SeeleError("INVALID_MANIFEST", "Manifest file path is unsupported on this platform")
    return path


def _resolved(path):
    return Path(path).expanduser().resolve()


def _is_root(path):
    return path == Path(path.anchor)


def _reject_symlink_components(path):
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.exists() and current.is_symlink():
            raise SeeleError("INVALID_REQUEST", "Cache path may not contain symbolic links")


def validate_cache_root(cache_root, protected_paths=(), require_sentinel=False):
    raw = Path(cache_root).expanduser()
    _reject_symlink_components(raw.absolute())
    root = raw.resolve()
    home = Path.home().resolve()
    dangerous = {
        home,
        (home / "Desktop").resolve(),
        (home / "Documents").resolve(),
        (home / "Downloads").resolve(),
    }
    dangerous.update(_resolved(value) for value in protected_paths if value)
    if _is_root(root) or root in dangerous:
        raise SeeleError("INVALID_REQUEST", "Cache directory is a protected location")
    sentinel = root / SENTINEL
    if require_sentinel:
        if root.is_symlink() or not sentinel.is_file() or sentinel.is_symlink():
            raise SeeleError("INVALID_REQUEST", "Cache directory is not managed by SEELE")
        try:
            if sentinel.read_text(encoding="utf-8") != SENTINEL_CONTENT:
                raise SeeleError("INVALID_REQUEST", "Cache sentinel is invalid")
        except OSError as exc:
            raise SeeleError("INVALID_REQUEST", "Cache sentinel cannot be read") from exc
    return root


def ensure_cache_root(cache_root, protected_paths=()):
    root = validate_cache_root(cache_root, protected_paths)
    root.mkdir(parents=True, exist_ok=True)
    sentinel = root / SENTINEL
    if sentinel.exists() and (sentinel.is_symlink() or not sentinel.is_file()):
        raise SeeleError("INVALID_REQUEST", "Cache sentinel is unsafe")
    if not sentinel.exists():
        sentinel.write_text(SENTINEL_CONTENT, encoding="utf-8")
    return validate_cache_root(root, protected_paths, require_sentinel=True)


def resolve_cache_path(root, relative):
    rel = safe_relative_path(relative)
    root_path = Path(root).resolve()
    candidate = root_path.joinpath(*rel.parts).resolve()
    try:
        candidate.relative_to(root_path)
    except ValueError as exc:
        raise SeeleError("INVALID_MANIFEST", "File path escapes cache directory") from exc
    return candidate


def new_instance_id():
    return str(uuid.uuid4())


def transfer_dir(cache_root, transfer_id, instance_id, create=False):
    try:
        transfer_id = str(uuid.UUID(str(transfer_id)))
        instance_id = str(uuid.UUID(str(instance_id)))
    except (ValueError, AttributeError) as exc:
        raise SeeleError("INVALID_MANIFEST", "Transfer or instance identifier is invalid") from exc
    root = validate_cache_root(cache_root, require_sentinel=True)
    candidate = root / transfer_id / instance_id
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SeeleError("INVALID_MANIFEST", "Transfer cache path is unsafe") from exc
    if create:
        resolved.mkdir(parents=True, exist_ok=False)
    return resolved


def transfer_root(cache_root, transfer_id):
    try:
        transfer_id = str(uuid.UUID(str(transfer_id)))
    except (ValueError, AttributeError) as exc:
        raise SeeleError("INVALID_REQUEST", "Transfer identifier is invalid") from exc
    root = validate_cache_root(cache_root, require_sentinel=True)
    candidate = (root / transfer_id).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SeeleError("INVALID_REQUEST", "Transfer cache path is unsafe") from exc
    return candidate


def clear_cache(cache_root, protected_paths=()):
    root = validate_cache_root(cache_root, protected_paths, require_sentinel=True)
    failures = []
    for child in root.iterdir():
        if child.name == SENTINEL:
            continue
        try:
            uuid.UUID(child.name)
        except (ValueError, AttributeError):
            continue
        try:
            if child.is_symlink() or not child.is_dir():
                raise OSError("unsafe managed entry")
            shutil.rmtree(child)
        except OSError:
            failures.append(child.name)
    if failures:
        raise SeeleError("INTERNAL_ERROR", "Some managed cache entries could not be removed", 500, True, "cache")


def default_cache_dir():
    return os.path.join(os.path.expanduser("~"), ".seele", "blender-cache")
