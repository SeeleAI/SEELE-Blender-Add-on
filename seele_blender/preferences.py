import os
import uuid

import bpy
from bpy.props import StringProperty

from .bridge.cors import normalize_origin
from .bridge.server import RuntimeConfig
from .errors import SeeleError
from .importers import available_importers
from .release_config import (
    BUILD_CHANNEL,
    BUILD_LABEL,
    DEFAULT_BRIDGE_PORT,
    DEFAULT_DOWNLOAD_HOSTS,
    DEFAULT_PRODUCTION_ORIGIN,
)
from .transfer.paths import default_cache_dir, ensure_cache_root


class SEELE_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    receiver_id: StringProperty(name="Receiver ID", default="", options={"HIDDEN"})

    def draw(self, context):
        layout = self.layout
        layout.label(text="SEELE Transfer is ready to use", icon="CHECKMARK")
        layout.label(text="Install and enable the add-on, then send models from the SEELE website.")
        layout.label(text=f"Build channel: {BUILD_LABEL}")
        layout.separator()
        layout.label(text="No website address, port, or download host setup is required.", icon="INFO")


def get_preferences(context=None):
    context = context or bpy.context
    return context.preferences.addons[__package__].preferences


def make_runtime_config(addon_version, blender_version, context=None):
    prefs = get_preferences(context)
    if not prefs.receiver_id:
        prefs.receiver_id = str(uuid.uuid4())
    cache_dir = bpy.path.abspath(default_cache_dir())
    blend_dir = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else ""
    config_dir = bpy.utils.user_resource("CONFIG")
    cache_dir = str(ensure_cache_root(cache_dir, (blend_dir, config_dir)))
    hosts = tuple(sorted({_normalize_download_host(value) for value in DEFAULT_DOWNLOAD_HOSTS}))
    origins = set()
    origin = normalize_origin(DEFAULT_PRODUCTION_ORIGIN)
    if not origin:
        raise SeeleError("INVALID_REQUEST", "Configured Web Origin is invalid")
    origins.add(origin)
    readiness = available_importers(bpy)
    formats = tuple(sorted(fmt for fmt, available in readiness.items() if available))
    return RuntimeConfig(
        port=DEFAULT_BRIDGE_PORT,
        cache_dir=cache_dir,
        download_hosts=hosts,
        allowed_origins=frozenset(origins),
        receiver_id=prefs.receiver_id,
        addon_version=addon_version,
        blender_version=blender_version,
        formats=formats,
        importer_readiness=tuple(sorted(readiness.items())),
        legacy_enabled=False,
        legacy_consume_url="",
        build_channel=BUILD_CHANNEL,
        build_label=BUILD_LABEL,
    )


def _normalize_download_host(value):
    value = value.strip().lower().rstrip(".")
    if not value or "*" in value or "://" in value or "/" in value or "@" in value:
        raise SeeleError("INVALID_REQUEST", "Download host allowlist contains an invalid entry")
    host, separator, port = value.rpartition(":")
    if separator:
        if not host or not port.isdigit() or not 1 <= int(port) <= 65535:
            raise SeeleError("INVALID_REQUEST", "Download host port is invalid")
    return value
