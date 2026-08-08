import copy
import threading
import time
from collections import OrderedDict

from ..errors import SeeleError
from .paths import new_instance_id


TERMINAL = {"completed", "completed_with_warnings", "failed", "cancelled"}
TRANSITIONS = {
    "accepted": {"downloading", "cancelled", "failed"},
    "downloading": {"verifying", "cancelled", "failed"},
    "verifying": {"queued", "cancelled", "failed"},
    "queued": {"importing_geometry", "cancelled", "failed"},
    "importing_geometry": {"importing_materials", "completed", "completed_with_warnings", "cancel_pending", "failed"},
    "importing_materials": {"completed", "completed_with_warnings", "cancel_pending", "failed"},
    "cancel_pending": {"cancelled", "failed"},
}
_PRIVATE = {"cancelRequested", "localFiles", "manifest", "legacyEnvelope", "instanceId", "attemptHistory"}


class TransferStateStore:
    def __init__(self, limit=100):
        self._lock = threading.RLock()
        self._items = OrderedDict()
        self._limit = limit

    def create(self, transfer_id, protocol, instance_id=None, manifest=None, legacy_envelope=None):
        with self._lock:
            if transfer_id in self._items:
                raise SeeleError("TRANSFER_CONFLICT", "Transfer id already exists", 409, False, "accepted")
            self._items[transfer_id] = {
                "transferId": transfer_id,
                "protocol": protocol,
                "state": "accepted",
                "stage": "queued",
                "progress": 0,
                "warnings": [],
                "error": None,
                "canRetryImport": False,
                "displayName": "",
                "updatedAt": time.time(),
                "cancelRequested": False,
                "manifest": manifest,
                "legacyEnvelope": legacy_envelope,
                "localFiles": None,
                "instanceId": instance_id or new_instance_id(),
                "attempt": 1,
                "attemptHistory": [],
            }
            self._items.move_to_end(transfer_id)
            self._evict_terminal()
            return self.get(transfer_id)

    def update(self, transfer_id, state=None, stage=None, progress=None, expected=None, **fields):
        with self._lock:
            item = self._require(transfer_id)
            if expected is not None:
                valid = {expected} if isinstance(expected, str) else set(expected)
                if item["state"] not in valid:
                    raise SeeleError("TRANSFER_CONFLICT", "Transfer state changed", 409, True, item["stage"])
            if state and state != item["state"]:
                if item["state"] in TERMINAL or state not in TRANSITIONS.get(item["state"], set()):
                    raise SeeleError("TRANSFER_CONFLICT", "Illegal transfer state transition", 409, False, item["stage"])
                item["state"] = state
            if stage is not None:
                item["stage"] = stage
            if progress is not None:
                item["progress"] = max(0, min(100, int(progress)))
            item.update(fields)
            item["updatedAt"] = time.time()
            return copy.deepcopy(self._public(item))

    def fail(self, transfer_id, error):
        with self._lock:
            item = self._require(transfer_id)
            if item["state"] in TERMINAL:
                return copy.deepcopy(self._public(item))
            if not isinstance(error, SeeleError):
                error = SeeleError("INTERNAL_ERROR", "Transfer failed", 500, True, item["stage"])
            return self.update(
                transfer_id,
                state="failed",
                stage=error.stage or item["stage"],
                error=error.payload(item["stage"]),
                canRetryImport=bool(
                    error.retryable
                    and (error.stage or item["stage"]) in {"geometry", "materials"}
                    and item.get("localFiles")
                    and item.get("manifest")
                ),
            )

    def request_cancel(self, transfer_id):
        with self._lock:
            item = self._require(transfer_id)
            if item["state"] in TERMINAL or item["state"] == "cancel_pending":
                return copy.deepcopy(self._public(item))
            item["cancelRequested"] = True
            if item["state"].startswith("importing"):
                return self.update(transfer_id, state="cancel_pending", stage="cancel_pending")
            return self.update(transfer_id, state="cancelled", stage="cancelled")

    def finish_cancel(self, transfer_id):
        return self.update(transfer_id, state="cancelled", stage="cancelled", expected="cancel_pending")

    def is_cancelled(self, transfer_id):
        with self._lock:
            item = self._require(transfer_id)
            return item["cancelRequested"] or item["state"] in {"cancelled", "cancel_pending"}

    def begin_import_retry(self, transfer_id):
        with self._lock:
            item = self._require(transfer_id)
            error = item.get("error") or {}
            if item["state"] != "failed" or not item.get("canRetryImport") or not error.get("retryable") or not item.get("localFiles") or not item.get("manifest"):
                raise SeeleError("TRANSFER_CONFLICT", "This transfer cannot be retried locally", 409)
            item["attemptHistory"].append(copy.deepcopy(self._public(item)))
            item.update({
                "state": "queued",
                "stage": "queued",
                "progress": 85,
                "warnings": [],
                "error": None,
                "canRetryImport": False,
                "cancelRequested": False,
                "instanceId": new_instance_id(),
                "attempt": item["attempt"] + 1,
                "updatedAt": time.time(),
            })
            return copy.deepcopy(self._public(item))

    def get(self, transfer_id, internal=False):
        with self._lock:
            item = self._require(transfer_id)
            return copy.deepcopy(item if internal else self._public(item))

    def recent(self, count=5):
        with self._lock:
            values = list(self._items.values())[-count:]
            return [copy.deepcopy(self._public(item)) for item in reversed(values)]

    def _require(self, transfer_id):
        if transfer_id not in self._items:
            raise SeeleError("INVALID_REQUEST", "Transfer not found", 404)
        return self._items[transfer_id]

    def _evict_terminal(self):
        while len(self._items) > self._limit:
            key = next((key for key, value in self._items.items() if value["state"] in TERMINAL), None)
            if key is None:
                break
            self._items.pop(key, None)

    @staticmethod
    def _public(item):
        return {key: copy.deepcopy(value) for key, value in item.items() if key not in _PRIVATE}
