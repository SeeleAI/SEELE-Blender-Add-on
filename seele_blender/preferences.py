import os
import uuid

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty

from .bridge.cors import allowed_origins, normalize_origin
from .bridge.server import RuntimeConfig
from .errors import SeeleError
from .importers import available_importers
from .transfer.paths import default_cache_dir, ensure_cache_root


class SEELE_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    port: IntProperty(name="Bridge Port", default=9878, min=1024, max=65535)
    cache_dir: StringProperty(name="Cache Directory", subtype="DIR_PATH", default=default_cache_dir())
    production_origin: StringProperty(name="Production Origin", default="")
    feature_origin: StringProperty(name="Feature Origin", default="")
    test_origin: StringProperty(name="Test Origin", default="")
    development_enabled: BoolProperty(name="Enable Development Origins", default=False)
    development_origins: StringProperty(name="Development Origins", default="http://localhost:3000")
    legacy_enabled: BoolProperty(name="Enable Legacy Consume Protocol", default=False)
    legacy_consume_url: StringProperty(name="Legacy BFF Consume URL", default="")
    download_hosts: StringProperty(name="Download Host Allowlist", description="Comma-separated exact hostnames", default="")
    receiver_id: StringProperty(name="Receiver ID", default="", options={"HIDDEN"})

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "port")
        layout.prop(self, "cache_dir")
        layout.prop(self, "production_origin")
        layout.prop(self, "feature_origin")
        layout.prop(self, "test_origin")
        layout.prop(self, "download_hosts")
        layout.separator()
        layout.prop(self, "development_enabled")
        if self.development_enabled:
            layout.prop(self, "development_origins")
        layout.separator()
        layout.prop(self, "legacy_enabled")
        if self.legacy_enabled:
            box = layout.box()
            box.alert = True
            box.label(text="Legacy protocol is deprecated and will be removed in 0.3.0", icon="ERROR")
            box.prop(self, "legacy_consume_url")
        layout.label(text="Restart Bridge after changing network settings.", icon="INFO")


def get_preferences(context=None):
    context = context or bpy.context
    return context.preferences.addons[__package__].preferences


def make_runtime_config(addon_version, blender_version, context=None):
    prefs = get_preferences(context)
    if not prefs.receiver_id:
        prefs.receiver_id = str(uuid.uuid4())
    cache_dir = bpy.path.abspath(prefs.cache_dir or default_cache_dir())
    blend_dir = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else ""
    config_dir = bpy.utils.user_resource("CONFIG")
    cache_dir = str(ensure_cache_root(cache_dir, (blend_dir, config_dir)))
    hosts = tuple(sorted({_normalize_download_host(value) for value in prefs.download_hosts.replace("\n", ",").split(",") if value.strip()}))
    origins = set()
    for value in (prefs.production_origin, prefs.feature_origin, prefs.test_origin):
        if value.strip():
            origin = normalize_origin(value)
            if not origin:
                raise SeeleError("INVALID_REQUEST", "Configured Web Origin is invalid")
            origins.add(origin)
    origins.update(allowed_origins("", prefs.development_origins, prefs.development_enabled))
    readiness = available_importers(bpy)
    formats = tuple(sorted(fmt for fmt, available in readiness.items() if available))
    if prefs.legacy_enabled and not prefs.legacy_consume_url.strip():
        raise SeeleError("INVALID_REQUEST", "Legacy Consume URL is required when legacy mode is enabled")
    return RuntimeConfig(
        port=prefs.port,
        cache_dir=cache_dir,
        download_hosts=hosts,
        allowed_origins=frozenset(origins),
        receiver_id=prefs.receiver_id,
        addon_version=addon_version,
        blender_version=blender_version,
        formats=formats,
        importer_readiness=tuple(sorted(readiness.items())),
        legacy_enabled=prefs.legacy_enabled,
        legacy_consume_url=prefs.legacy_consume_url.strip(),
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
