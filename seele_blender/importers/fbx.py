def operator_and_options(bpy, filepath, manifest):
    return getattr(bpy.ops.import_scene, "fbx", None), {"filepath": filepath}
