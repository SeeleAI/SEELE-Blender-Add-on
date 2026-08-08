def operator_and_options(bpy, filepath, manifest):
    return getattr(bpy.ops.wm, "stl_import", None), {"filepath": filepath}


def apply_units(objects, manifest):
    factor = manifest.get("unitScaleMeters")
    if factor is None or factor == 1.0:
        return
    for obj in objects:
        obj.scale = tuple(component * factor for component in obj.scale)
