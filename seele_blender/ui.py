import json
import os

import bpy
from bpy.props import StringProperty

from . import runtime
from .bridge import queue as bridge_queue
from .bridge import server
from .errors import SeeleError
from .release_config import BUILD_CHANNEL, BUILD_LABEL, DEFAULT_BRIDGE_PORT
from .transfer.manifest import DCC_PROTOCOL
from .transfer.paths import clear_cache, default_cache_dir, transfer_root


STATE_LABELS = {
    "accepted": "Received",
    "downloading": "Downloading",
    "verifying": "Verifying",
    "queued": "Waiting to import",
    "importing_geometry": "Importing model",
    "importing_materials": "Processing materials",
    "cancel_pending": "Cancelling",
    "cancelled": "Cancelled",
    "completed": "Completed",
    "completed_with_warnings": "Completed with warnings",
    "failed": "Failed",
}

ERROR_LABELS = {
    "DOWNLOAD_EXPIRED": "The download authorization has expired. Please send the model again from SEELE.",
    "DOWNLOAD_HTTP_ERROR": "The download service is temporarily unavailable. Please try again later.",
    "DOWNLOAD_TLS_ERROR": "Could not securely connect to the download service.",
    "DOWNLOAD_TIMEOUT": "The download timed out. Check your connection and send the model again.",
    "DOWNLOAD_NETWORK_ERROR": "Could not connect to the download service. Check your network connection.",
    "DOWNLOAD_WRITE_FAILED": "Could not write to the local cache. Check disk space and permissions.",
    "DOWNLOAD_HOST_BLOCKED": "The download address did not pass the security check.",
    "DOWNLOAD_SIZE_MISMATCH": "The downloaded file size does not match the expected size.",
    "DOWNLOAD_HASH_MISMATCH": "The downloaded file failed its integrity check.",
    "IMPORT_OPERATOR_UNAVAILABLE": "This Blender installation cannot import this file format.",
    "IMPORT_GEOMETRY_FAILED": "The model could not be imported.",
    "IMPORT_MATERIAL_FAILED": "The materials could not be imported.",
    "INTERNAL_ERROR": "An internal error occurred. Copy the diagnostics and contact support.",
}


def _cache_root():
    return runtime.CONFIG.cache_dir if runtime.CONFIG else bpy.path.abspath(default_cache_dir())


def _friendly_warning(message):
    if "no SHA-256" in message:
        return "The source file did not include an integrity checksum."
    if "no declared size" in message:
        return "The source file did not include its size; safe limits were applied."
    if "FBX materials" in message:
        return "Some FBX materials may need to be checked manually."
    return str(message)


class SEELE_OT_bridge_start(bpy.types.Operator):
    bl_idname = "seele.bridge_start"
    bl_label = "Start SEELE Connection"

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
    bl_label = "Stop SEELE Connection"

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
        root = _cache_root()
        path = str(transfer_root(root, self.transfer_id)) if self.transfer_id else root
        os.makedirs(path, exist_ok=True)
        bpy.ops.wm.path_open(filepath=path)
        return {"FINISHED"}


class SEELE_OT_clear_cache(bpy.types.Operator):
    bl_idname = "seele.clear_cache"
    bl_label = "Clear SEELE Cache"

    def invoke(self, context, event):
        root = _cache_root()
        self.report({"WARNING"}, f"The SEELE cache will be cleared: {os.path.abspath(root)}")
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        active = [item for item in runtime.STATE.recent(10000) if item["state"] not in {"completed", "completed_with_warnings", "failed", "cancelled"}]
        if active:
            self.report({"WARNING"}, "Wait for active transfers to finish, or cancel them first.")
            return {"CANCELLED"}
        root = _cache_root()
        blend_dir = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else ""
        clear_cache(root, (blend_dir, bpy.utils.user_resource("CONFIG")))
        self.report({"INFO"}, "The SEELE cache has been cleared.")
        return {"FINISHED"}


class SEELE_OT_copy_diagnostics(bpy.types.Operator):
    bl_idname = "seele.copy_diagnostics"
    bl_label = "Copy Diagnostics"

    def execute(self, context):
        from . import ADDON_VERSION
        config = runtime.CONFIG
        summary = {
            "service": "seele-dcc-receiver",
            "dcc": "blender",
            "receiverVersion": ADDON_VERSION,
            "hostVersion": bpy.app.version_string,
            "buildChannel": config.build_channel if config else BUILD_CHANNEL,
            "bridge": "running" if server.is_running() else ("error" if runtime.BRIDGE_ERROR else "stopped"),
            "port": config.port if config else DEFAULT_BRIDGE_PORT,
            "protocols": [DCC_PROTOCOL],
            "formats": list(config.formats) if config else [],
            "transfers": runtime.STATE.recent(5),
        }
        context.window_manager.clipboard = json.dumps(summary, ensure_ascii=False, indent=2)
        self.report({"INFO"}, "Diagnostics copied. Download credentials and local paths are not included.")
        return {"FINISHED"}


class SEELE_OT_frame_transfer(bpy.types.Operator):
    bl_idname = "seele.frame_transfer"
    bl_label = "Frame Imported Model"
    transfer_id: StringProperty()

    def execute(self, context):
        collection = next((item for item in bpy.data.collections if item.get("seele_transfer_id") == self.transfer_id), None)
        if collection is None:
            self.report({"WARNING"}, "The imported model could not be found.")
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
            self.report({"INFO"}, "The model is selected. Switch to a 3D View to frame it.")
        return {"FINISHED"}


class SEELE_PT_sidebar(bpy.types.Panel):
    bl_label = "SEELE Model Transfer"
    bl_idname = "SEELE_PT_sidebar"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "SEELE"

    def draw(self, context):
        from . import ADDON_VERSION
        layout = self.layout
        row = layout.row(align=True)
        running = server.is_running()
        bridge_state = "Ready" if running else ("Failed to start" if runtime.BRIDGE_ERROR else "Stopped")
        row.label(text=f"Connection: {bridge_state}", icon="CHECKMARK" if running else "CANCEL")
        row.operator("seele.bridge_stop" if running else "seele.bridge_start", text="Stop" if running else "Start")
        layout.label(text=f"SEELE Transfer {ADDON_VERSION} · {BUILD_LABEL}")
        if running:
            layout.label(text='Click "Send to Blender" on the SEELE website.', icon="INFO")
            ready = ", ".join(runtime.CONFIG.formats) or "None"
            layout.label(text=f"Supported formats: {ready}")
        elif runtime.BRIDGE_ERROR:
            layout.label(text="The connection could not start. Close other Blender instances and try again.", icon="ERROR")

        layout.separator()
        layout.label(text="Recent Transfers")
        transfers = runtime.STATE.recent(5)
        if not transfers:
            layout.label(text="No transfers yet.", icon="INFO")
        for item in transfers:
            box = layout.box()
            box.label(text=item.get("displayName") or item["transferId"][:12])
            box.label(text=f"{STATE_LABELS.get(item['state'], item['state'])}  {item['progress']}%")
            for warning in item.get("warnings", [])[:2]:
                box.label(text=_friendly_warning(warning)[:100], icon="INFO")
            if item.get("error"):
                code = item["error"]["code"]
                box.label(text=ERROR_LABELS.get(code, "Transfer failed. Please copy the diagnostics."), icon="CANCEL")
            actions = box.row(align=True)
            if item["state"] not in {"completed", "completed_with_warnings", "failed", "cancelled", "cancel_pending"}:
                op = actions.operator("seele.transfer_cancel", text="Cancel")
                op.transfer_id = item["transferId"]
            if item["state"] == "failed" and item.get("canRetryImport"):
                op = actions.operator("seele.transfer_retry", text="Retry Import")
                op.transfer_id = item["transferId"]
            elif item["state"] == "failed" and item.get("stage") in {"accepted", "downloading", "verifying"}:
                box.label(text="Return to the SEELE website and send the model again.", icon="INFO")
            op = actions.operator("seele.open_cache", text="View Files")
            op.transfer_id = item["transferId"]
            if item["state"] in {"completed", "completed_with_warnings"}:
                op = actions.operator("seele.frame_transfer", text="Frame Model")
                op.transfer_id = item["transferId"]

        layout.separator()
        row = layout.row(align=True)
        row.operator("seele.open_cache", text="Open Cache")
        row.operator("seele.clear_cache", text="Clear Cache")
        layout.operator("seele.copy_diagnostics", text="Copy Diagnostics")


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
