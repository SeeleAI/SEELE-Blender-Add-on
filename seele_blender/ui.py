import json
import os

import bpy
from bpy.props import StringProperty

from . import runtime
from .bridge import queue as bridge_queue
from .bridge import server
from .errors import SeeleError
from .preferences import get_preferences
from .transfer.manifest import DCC_PROTOCOL, LEGACY_PROTOCOL
from .transfer.paths import clear_cache, transfer_root


class SEELE_OT_bridge_start(bpy.types.Operator):
    bl_idname = "seele.bridge_start"
    bl_label = "Start SEELE Bridge"

    def execute(self, context):
        try:
            from . import start_bridge
            start_bridge(context)
        except SeeleError as exc:
            self.report({"ERROR"}, exc.message)
            return {"CANCELLED"}
        return {"FINISHED"}


class SEELE_OT_bridge_stop(bpy.types.Operator):
    bl_idname = "seele.bridge_stop"
    bl_label = "Stop SEELE Bridge"

    def execute(self, context):
        server.stop()
        return {"FINISHED"}


class SEELE_OT_transfer_cancel(bpy.types.Operator):
    bl_idname = "seele.transfer_cancel"
    bl_label = "Cancel Transfer"
    transfer_id: StringProperty()

    def execute(self, context):
        try:
            runtime.STATE.request_cancel(self.transfer_id)
            return {"FINISHED"}
        except SeeleError as exc:
            self.report({"ERROR"}, exc.message)
            return {"CANCELLED"}


class SEELE_OT_transfer_retry(bpy.types.Operator):
    bl_idname = "seele.transfer_retry"
    bl_label = "Retry Import"
    transfer_id: StringProperty()

    def execute(self, context):
        try:
            bridge_queue.retry_import(self.transfer_id)
            return {"FINISHED"}
        except SeeleError as exc:
            self.report({"ERROR"}, exc.message)
            return {"CANCELLED"}


class SEELE_OT_open_cache(bpy.types.Operator):
    bl_idname = "seele.open_cache"
    bl_label = "Open Cache Folder"
    transfer_id: StringProperty(default="")

    def execute(self, context):
        root = runtime.CONFIG.cache_dir if runtime.CONFIG else bpy.path.abspath(get_preferences(context).cache_dir)
        path = str(transfer_root(root, self.transfer_id)) if self.transfer_id else root
        os.makedirs(path, exist_ok=True)
        bpy.ops.wm.path_open(filepath=path)
        return {"FINISHED"}


class SEELE_OT_clear_cache(bpy.types.Operator):
    bl_idname = "seele.clear_cache"
    bl_label = "Clear SEELE Cache"

    def invoke(self, context, event):
        root = runtime.CONFIG.cache_dir if runtime.CONFIG else bpy.path.abspath(get_preferences(context).cache_dir)
        self.report({"WARNING"}, f"Clear managed cache contents: {os.path.abspath(root)}")
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        active = [item for item in runtime.STATE.recent(10000) if item["state"] not in {"completed", "completed_with_warnings", "failed", "cancelled"}]
        if active:
            self.report({"WARNING"}, "Wait for active transfers or cancel them first")
            return {"CANCELLED"}
        root = runtime.CONFIG.cache_dir if runtime.CONFIG else bpy.path.abspath(get_preferences(context).cache_dir)
        blend_dir = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else ""
        clear_cache(root, (blend_dir, bpy.utils.user_resource("CONFIG")))
        self.report({"INFO"}, "SEELE cache cleared")
        return {"FINISHED"}


class SEELE_OT_copy_diagnostics(bpy.types.Operator):
    bl_idname = "seele.copy_diagnostics"
    bl_label = "Copy Diagnostic Summary"

    def execute(self, context):
        from . import ADDON_VERSION
        config = runtime.CONFIG
        summary = {
            "service": "seele-dcc-receiver",
            "dcc": "blender",
            "receiverVersion": ADDON_VERSION,
            "hostVersion": bpy.app.version_string,
            "bridge": "running" if server.is_running() else ("error" if runtime.BRIDGE_ERROR else "stopped"),
            "port": config.port if config else get_preferences(context).port,
            "protocols": [DCC_PROTOCOL] + ([LEGACY_PROTOCOL] if config and config.legacy_enabled else []),
            "formats": list(config.formats) if config else [],
            "transfers": runtime.STATE.recent(5),
        }
        context.window_manager.clipboard = json.dumps(summary, ensure_ascii=False, indent=2)
        self.report({"INFO"}, "Sanitized diagnostic summary copied")
        return {"FINISHED"}


class SEELE_OT_frame_transfer(bpy.types.Operator):
    bl_idname = "seele.frame_transfer"
    bl_label = "Frame Imported Asset"
    transfer_id: StringProperty()

    def execute(self, context):
        collection = next((item for item in bpy.data.collections if item.get("seele_transfer_id") == self.transfer_id), None)
        if collection is None:
            self.report({"WARNING"}, "Imported collection was not found")
            return {"CANCELLED"}
        for obj in context.selected_objects:
            obj.select_set(False)
        objects = list(collection.all_objects)
        for obj in objects:
            obj.select_set(True)
        if objects:
            context.view_layer.objects.active = objects[0]
        try:
            bpy.ops.view3d.view_selected(use_all_regions=False)
        except RuntimeError:
            self.report({"INFO"}, "Objects selected; switch to a 3D View to frame them")
        return {"FINISHED"}


class SEELE_PT_sidebar(bpy.types.Panel):
    bl_label = "SEELE Transfer"
    bl_idname = "SEELE_PT_sidebar"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "SEELE"

    def draw(self, context):
        from . import ADDON_VERSION
        layout = self.layout
        row = layout.row(align=True)
        running = server.is_running()
        bridge_state = "Running" if running else ("Error" if runtime.BRIDGE_ERROR else "Stopped")
        row.label(text=f"Bridge: {bridge_state}", icon="CHECKMARK" if running else "CANCEL")
        row.operator("seele.bridge_stop" if running else "seele.bridge_start", text="Stop" if running else "Start")
        layout.label(text=f"Blender {bpy.app.version_string} / Add-on {ADDON_VERSION}")
        if running:
            layout.label(text=f"127.0.0.1:{runtime.CONFIG.port}")
            layout.label(text=f"Receiver: {runtime.CONFIG.receiver_id[:12]}…")
            layout.label(text=f"Protocols: {', '.join([DCC_PROTOCOL] + ([LEGACY_PROTOCOL] if runtime.CONFIG.legacy_enabled else []))}")
            ready = ", ".join(runtime.CONFIG.formats) or "none"
            layout.label(text=f"Importers ready: {ready}")
            if runtime.CONFIG.legacy_enabled:
                warning = layout.box()
                warning.alert = True
                warning.label(text="Legacy consume enabled; removal planned for 0.3.0", icon="ERROR")
        elif runtime.BRIDGE_ERROR:
            layout.label(text=runtime.BRIDGE_ERROR, icon="ERROR")

        layout.separator()
        layout.label(text="Recent Transfers")
        transfers = runtime.STATE.recent(5)
        if not transfers:
            layout.label(text="No transfers yet", icon="INFO")
        for item in transfers:
            box = layout.box()
            box.label(text=item.get("displayName") or item["transferId"][:12])
            box.label(text=f"{item['state']} / {item['stage']}  {item['progress']}%")
            for warning in item.get("warnings", [])[:2]:
                box.label(text=str(warning)[:100], icon="ERROR")
            if item.get("error"):
                box.label(text=item["error"]["code"], icon="CANCEL")
            actions = box.row(align=True)
            if item["state"] not in {"completed", "completed_with_warnings", "failed", "cancelled", "cancel_pending"}:
                op = actions.operator("seele.transfer_cancel", text="Cancel")
                op.transfer_id = item["transferId"]
            if item["state"] == "failed" and item.get("canRetryImport"):
                op = actions.operator("seele.transfer_retry", text="Retry Import")
                op.transfer_id = item["transferId"]
            elif item["state"] == "failed" and item.get("stage") in {"accepted", "downloading", "verifying"}:
                box.label(text="Create a new transfer from SEELE Web", icon="INFO")
            op = actions.operator("seele.open_cache", text="Cache")
            op.transfer_id = item["transferId"]
            if item["state"] in {"completed", "completed_with_warnings"}:
                op = actions.operator("seele.frame_transfer", text="Frame")
                op.transfer_id = item["transferId"]

        layout.separator()
        row = layout.row(align=True)
        row.operator("seele.open_cache", text="Open Cache")
        row.operator("seele.clear_cache", text="Clear Cache")
        layout.operator("seele.copy_diagnostics", text="Copy Diagnostic Summary")
        root = runtime.CONFIG.cache_dir if runtime.CONFIG else bpy.path.abspath(get_preferences(context).cache_dir)
        layout.label(text=f"Cache: {os.path.abspath(root)}")


CLASSES = (
    SEELE_OT_bridge_start,
    SEELE_OT_bridge_stop,
    SEELE_OT_transfer_cancel,
    SEELE_OT_transfer_retry,
    SEELE_OT_open_cache,
    SEELE_OT_clear_cache,
    SEELE_OT_copy_diagnostics,
    SEELE_OT_frame_transfer,
    SEELE_PT_sidebar,
)
