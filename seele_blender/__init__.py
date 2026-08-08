bl_info = {
    "name": "SEELE Transfer",
    "author": "SEELE",
    "version": (0, 2, 1),
    "blender": (4, 0, 0),
    "location": "3D View > Sidebar > SEELE",
    "description": "Securely receive and import SEELE assets",
    "category": "Import-Export",
}

ADDON_VERSION = ".".join(str(value) for value in bl_info["version"])
try:
    import bpy
except ModuleNotFoundError:  # Allows security/state unit tests outside Blender.
    bpy = None


if bpy is not None:
    import queue

    from . import runtime
    from .bridge import server
    from .errors import CancelledError, SeeleError
    from .importers import import_asset, rollback_import
    from .preferences import SEELE_AddonPreferences, make_runtime_config
    from .ui import CLASSES as UI_CLASSES

    CLASSES = (SEELE_AddonPreferences,) + UI_CLASSES

    def start_bridge(context=None):
        config = make_runtime_config(ADDON_VERSION, bpy.app.version_string, context)
        return server.start(config)

    def pump_jobs():
        try:
            transfer_id = runtime.IMPORT_QUEUE.get_nowait()
        except queue.Empty:
            return 0.2
        snapshot = None
        try:
            item = runtime.STATE.get(transfer_id, internal=True)
            if item["state"] == "cancelled":
                return 0.2
            runtime.STATE.update(transfer_id, state="importing_geometry", stage="geometry", progress=90, expected="queued")
            result = import_asset(
                bpy,
                bpy.context,
                item["manifest"],
                item["localFiles"],
                cancelled=lambda: runtime.STATE.is_cancelled(transfer_id),
            )
            snapshot = result.pop("_snapshot")
            if runtime.STATE.is_cancelled(transfer_id):
                rollback_import(bpy, snapshot)
                runtime.STATE.finish_cancel(transfer_id)
                return 0.2
            warnings = list(item.get("warnings", [])) + list(result.get("warnings", []))
            runtime.STATE.update(
                transfer_id,
                state="importing_materials",
                stage="materials",
                progress=97,
                warnings=warnings,
                expected="importing_geometry",
            )
            if runtime.STATE.is_cancelled(transfer_id):
                rollback_import(bpy, snapshot)
                runtime.STATE.finish_cancel(transfer_id)
                return 0.2
            state = "completed_with_warnings" if warnings else "completed"
            runtime.STATE.update(transfer_id, state=state, stage="completed", progress=100, result=result, expected="importing_materials")
        except CancelledError:
            try:
                current = runtime.STATE.get(transfer_id)
                if current["state"] == "cancel_pending":
                    runtime.STATE.finish_cancel(transfer_id)
                elif current["state"] not in {"cancelled", "failed"}:
                    runtime.STATE.request_cancel(transfer_id)
            except SeeleError:
                pass
        except Exception as exc:
            try:
                current = runtime.STATE.get(transfer_id)
                if current["state"] == "cancel_pending" and snapshot is not None:
                    rollback_import(bpy, snapshot)
                    runtime.STATE.finish_cancel(transfer_id)
                    return 0.2
                error = exc if isinstance(exc, SeeleError) else SeeleError("INTERNAL_ERROR", "Asset import failed", 500, True, "geometry")
                runtime.STATE.fail(transfer_id, error)
            except SeeleError:
                pass
        return 0.2

    def register():
        for cls in CLASSES:
            bpy.utils.register_class(cls)
        if not bpy.app.timers.is_registered(pump_jobs):
            bpy.app.timers.register(pump_jobs, first_interval=0.2, persistent=True)
        try:
            start_bridge()
        except Exception as exc:
            print(f"SEELE Bridge not started: {getattr(exc, 'code', type(exc).__name__)}")

    def unregister():
        server.stop()
        if bpy.app.timers.is_registered(pump_jobs):
            bpy.app.timers.unregister(pump_jobs)
        for cls in reversed(CLASSES):
            bpy.utils.unregister_class(cls)
        runtime.reset()
else:
    def register():
        raise RuntimeError("SEELE Transfer must be registered inside Blender 4.0+")

    def unregister():
        return None
