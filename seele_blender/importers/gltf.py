def operator_and_options(bpy, filepath, manifest):
    return getattr(bpy.ops.import_scene, "gltf", None), {"filepath": filepath}
