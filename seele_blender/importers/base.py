import re

from ..errors import CancelledError, SeeleError
from . import fbx, gltf, stl


IMPORTERS = {"glb": gltf, "gltf": gltf, "fbx": fbx, "stl": stl}
DATA_COLLECTIONS = ("objects", "collections", "materials", "images", "meshes", "armatures", "actions")


def _supported_kwargs(operator, options):
    try:
        properties = {item.identifier for item in operator.get_rna_type().properties}
        return {key: value for key, value in options.items() if key in properties}
    except (AttributeError, RuntimeError):
        return options


def _operator_available(operator):
    if operator is None:
        return False
    try:
        operator.get_rna_type()
        return True
    except (AttributeError, RuntimeError):
        return False


def available_importers(bpy):
    readiness = {}
    for fmt, module in IMPORTERS.items():
        operator, _ = module.operator_and_options(bpy, "", {})
        readiness[fmt] = _operator_available(operator)
    return readiness


def _snapshot(bpy):
    return {name: set(getattr(bpy.data, name)) for name in DATA_COLLECTIONS}


def rollback_import(bpy, snapshot):
    failures = []
    for datablock in list(set(bpy.data.objects) - snapshot["objects"]):
        try:
            bpy.data.objects.remove(datablock, do_unlink=True)
        except Exception:
            failures.append("object")
    for name in ("collections", "actions", "armatures", "meshes", "materials", "images"):
        collection = getattr(bpy.data, name)
        for datablock in list(set(collection) - snapshot[name]):
            try:
                if name == "collections" or getattr(datablock, "users", 0) == 0:
                    collection.remove(datablock)
            except Exception:
                failures.append(name)
    if failures:
        raise SeeleError("IMPORT_ROLLBACK_FAILED", "Imported data could not be fully rolled back", 500, False, "rollback")


def _collection_name(bpy, display_name):
    safe = re.sub(r"[^\w .-]+", "_", str(display_name or "Asset"), flags=re.UNICODE).strip(" ._") or "Asset"
    base = f"SEELE_{safe}"[:63]
    name = base
    suffix = 2
    while bpy.data.collections.get(name) is not None:
        ending = f"_{suffix}"
        name = base[:63 - len(ending)] + ending
        suffix += 1
    return name


def _organize(bpy, context, objects, manifest):
    collection = bpy.data.collections.new(_collection_name(bpy, manifest.get("displayName")))
    context.scene.collection.children.link(collection)
    collection["seele_transfer_id"] = manifest["transferId"]
    for obj in objects:
        for source in list(obj.users_collection):
            source.objects.unlink(obj)
        collection.objects.link(obj)
    return collection


def import_asset(bpy, context, manifest, local_files, cancelled=lambda: False):
    module = IMPORTERS.get(manifest["format"])
    if module is None:
        raise SeeleError("UNSUPPORTED_FORMAT", "No importer is available for this format")
    filepath = local_files.get(manifest["entryFilePath"])
    if not filepath:
        raise SeeleError("DEPENDENCY_MISSING", "Downloaded entry file is missing")
    operator, options = module.operator_and_options(bpy, filepath, manifest)
    if not _operator_available(operator):
        raise SeeleError("IMPORT_OPERATOR_UNAVAILABLE", "Blender import operator is unavailable", 409, False, "geometry")
    if cancelled():
        raise CancelledError("geometry")
    snapshot = _snapshot(bpy)
    try:
        result = operator(**_supported_kwargs(operator, options))
    except Exception as exc:
        try:
            rollback_import(bpy, snapshot)
        except SeeleError:
            raise
        raise SeeleError("IMPORT_GEOMETRY_FAILED", "Blender geometry import failed", 500, True, "geometry") from exc
    if "FINISHED" not in result:
        rollback_import(bpy, snapshot)
        raise SeeleError("IMPORT_GEOMETRY_FAILED", "Blender geometry import did not finish", 500, True, "geometry")
    if cancelled():
        rollback_import(bpy, snapshot)
        raise CancelledError("geometry")
    imported = list(set(bpy.data.objects) - snapshot["objects"])
    if not imported:
        rollback_import(bpy, snapshot)
        raise SeeleError("IMPORT_GEOMETRY_FAILED", "Blender importer created no objects", 500, True, "geometry")
    if manifest["format"] == "stl":
        stl.apply_units(imported, manifest)
    try:
        collection = _organize(bpy, context, imported, manifest)
    except Exception as exc:
        rollback_import(bpy, snapshot)
        raise SeeleError("IMPORT_GEOMETRY_FAILED", "Imported objects could not be organized", 500, True, "geometry") from exc
    if cancelled():
        rollback_import(bpy, snapshot)
        raise CancelledError("geometry")
    warnings = []
    if manifest["format"] == "fbx":
        warnings.append("FBX materials and external textures are best-effort")
    return {"collection": collection.name, "objects": len(imported), "warnings": warnings, "_snapshot": snapshot}
