import json
import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .. import runtime
from .challenge import ChallengeStore
from ..errors import SeeleError
from ..transfer.manifest import DCC_PROTOCOL, LEGACY_PROTOCOL
from .cors import is_origin_allowed, normalize_origin
from .queue import receive


TRANSFER_PATH = re.compile(r"^/v1/transfers/([^/]+)(/cancel)?$")


@dataclass(frozen=True)
class RuntimeConfig:
    port: int
    cache_dir: str
    download_hosts: tuple
    allowed_origins: frozenset
    receiver_id: str
    addon_version: str
    blender_version: str
    formats: tuple
    importer_readiness: tuple
    legacy_enabled: bool = False
    legacy_consume_url: str = ""
    build_channel: str = "public"
    build_label: str = "Public Release"


class BridgeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler):
        super().__init__(address, handler)
        self.rate_limiter = RateLimiter()


class RateLimiter:
    def __init__(self, max_requests=20, window_seconds=60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._events = defaultdict(deque)

    def allow(self, key):
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            while events and events[0] <= now - self.window_seconds:
                events.popleft()
            if len(events) >= self.max_requests:
                return False
            events.append(now)
            return True


class Handler(BaseHTTPRequestHandler):
    server_version = "SEELEBridge/0.2"
    sys_version = ""

    def log_message(self, fmt, *args):
        # Avoid leaking URLs, tokens and local paths through default request logs.
        return

    def do_OPTIONS(self):
        if not self._check_origin():
            return
        self.send_response(204)
        self._cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        if self.headers.get("Access-Control-Request-Private-Network", "").lower() == "true":
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "300")
        self.end_headers()

    def do_GET(self):
        if not self._check_origin():
            return
        try:
            if self.path == "/v1/health":
                config = runtime.CONFIG
                challenge, challenge_expires = runtime.CHALLENGES.issue(config.receiver_id, self._origin())
                protocols = [DCC_PROTOCOL]
                if config.legacy_enabled:
                    protocols.append(LEGACY_PROTOCOL)
                self._success(200, {
                    "service": "seele-dcc-receiver",
                    "dcc": "blender",
                    "receiverId": config.receiver_id,
                    "receiverVersion": config.addon_version,
                    "hostVersion": config.blender_version,
                    "buildChannel": config.build_channel,
                    "protocols": protocols,
                    "capabilities": {
                        "formats": list(config.formats),
                        "maxFiles": 128,
                        "maxTotalBytes": 1073741824,
                        "supportsStatus": True,
                        "supportsCancel": True,
                        "supportsRetryImport": True,
                        "supportsMaterials": False,
                        "importers": dict(config.importer_readiness),
                    },
                    "challenge": challenge,
                    "challengeExpiresAt": challenge_expires,
                })
                return
            match = TRANSFER_PATH.fullmatch(self.path)
            if match and not match.group(2):
                self._success(200, runtime.STATE.get(match.group(1)))
                return
            raise SeeleError("INVALID_REQUEST", "Route not found", 404)
        except SeeleError as exc:
            self._error(exc)

    def do_POST(self):
        if not self._check_origin():
            return
        try:
            if self.path == "/v1/transfers":
                if not self.server.rate_limiter.allow((self.client_address[0], self._origin())):
                    raise SeeleError("INVALID_REQUEST", "Receiver rate limit exceeded", 429, True, "accepted")
                self._success(202, receive(self._read_json(), self._origin()))
                return
            match = TRANSFER_PATH.fullmatch(self.path)
            if match and match.group(2):
                result = runtime.STATE.request_cancel(match.group(1))
                self._success(202 if result["state"] == "cancel_pending" else 200, result)
                return
            raise SeeleError("INVALID_REQUEST", "Route not found", 404)
        except SeeleError as exc:
            self._error(exc)
        except Exception:
            self._error(SeeleError("INTERNAL_ERROR", "Receiver could not process the request", 500, True))

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise SeeleError("INVALID_REQUEST", "Invalid Content-Length") from exc
        if length <= 0 or length > 2 * 1024 * 1024:
            raise SeeleError("INVALID_REQUEST", "Request body size is invalid", 413)
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SeeleError("INVALID_REQUEST", "Request body is not valid JSON") from exc

    def _check_origin(self):
        origin = self._origin()
        if origin and is_origin_allowed(origin, runtime.CONFIG.allowed_origins):
            return True
        self._error(SeeleError("ORIGIN_BLOCKED", "Origin is not allowed", 403), cors=False)
        return False

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", self._origin())
        self.send_header("Vary", "Origin")
        self.send_header("Cache-Control", "no-store")

    def _json(self, status, payload, cors=True):
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        if cors:
            self._cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _success(self, status, data):
        self._json(status, {"ok": True, "data": data})

    def _error(self, error, cors=True):
        self._json(error.http_status, {"ok": False, "error": error.payload()}, cors=cors)

    def _origin(self):
        return normalize_origin(self.headers.get("Origin", ""))


def start(config):
    if runtime.SERVER is not None:
        return runtime.SERVER
    runtime.CONFIG = config
    runtime.CHALLENGES = ChallengeStore(ttl=60, max_pending=32)
    runtime.BRIDGE_ERROR = None
    try:
        server = BridgeServer(("127.0.0.1", config.port), Handler)
    except OSError as exc:
        runtime.BRIDGE_ERROR = "Bridge port is unavailable"
        raise SeeleError("INTERNAL_ERROR", "Bridge port is unavailable", 500, True, "bridge") from exc
    thread = threading.Thread(target=server.serve_forever, name="SEELE-Bridge", daemon=True)
    thread.start()
    runtime.SERVER = server
    return server


def stop():
    server = runtime.SERVER
    runtime.SERVER = None
    if server is not None:
        for item in runtime.STATE.recent(10000):
            if item["state"] not in {"completed", "completed_with_warnings", "failed", "cancelled", "cancel_pending"}:
                try:
                    runtime.STATE.request_cancel(item["transferId"])
                except SeeleError:
                    pass
        server.shutdown()
        server.server_close()
        runtime.wait_workers(timeout=2.0)


def is_running():
    return runtime.SERVER is not None
