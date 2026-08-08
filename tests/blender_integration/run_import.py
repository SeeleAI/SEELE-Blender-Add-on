"""Usage: blender --background --factory-startup --python run_import.py -- fixture.glb [metersPerUnit]"""
import os
import sys
import uuid

import bpy


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from seele_blender.importers import import_asset


args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if not args:
    raise SystemExit("Fixture path required")
fixture = os.path.abspath(args[0])
fmt = os.path.splitext(fixture)[1].lower().lstrip(".")
transfer_id = str(uuid.uuid4())
manifest = {
    "transferId": transfer_id,
    "format": fmt,
    "displayName": "Integration Fixture",
    "entryFilePath": os.path.basename(fixture),
}
if fmt == "stl":
    manifest["unitScaleMeters"] = float(args[1]) if len(args) > 1 else 1.0
result = import_asset(bpy, bpy.context, manifest, {manifest["entryFilePath"]: fixture})
result.pop("_snapshot", None)
collection = bpy.data.collections[result["collection"]]
assert collection["seele_transfer_id"] == transfer_id
assert result["objects"] > 0
print("SEELE_INTEGRATION_OK", result)
