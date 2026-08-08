import secrets
import threading
import time
from datetime import datetime, timezone

from ..errors import SeeleError


class ChallengeStore:
    def __init__(self, ttl=60, max_pending=32):
        self.ttl = ttl
        self.max_pending = max_pending
        self._lock = threading.Lock()
        self._items = {}
        self._used = {}

    def issue(self, receiver_id, origin):
        now = time.monotonic()
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._prune(now)
            while len(self._items) >= self.max_pending:
                oldest = min(self._items, key=lambda key: self._items[key][0])
                self._items.pop(oldest, None)
            expiry = now + self.ttl
            self._items[token] = (expiry, receiver_id, origin)
        expires_at = datetime.fromtimestamp(time.time() + self.ttl, timezone.utc).isoformat().replace("+00:00", "Z")
        return token, expires_at

    def consume(self, token, receiver_id, origin):
        now = time.monotonic()
        with self._lock:
            self._prune_used(now)
            if token in self._used:
                raise SeeleError("CHALLENGE_REPLAYED", "Challenge was already used", 403)
            item = self._items.get(token)
            if item is None:
                raise SeeleError("CHALLENGE_REPLAYED", "Challenge is unknown", 403)
            expiry, expected_receiver, expected_origin = item
            if expiry <= now:
                self._items.pop(token, None)
                self._used[token] = now + self.ttl
                raise SeeleError("CHALLENGE_EXPIRED", "Challenge expired", 401)
            if receiver_id != expected_receiver:
                raise SeeleError("RECEIVER_MISMATCH", "Receiver does not match challenge", 403)
            if origin != expected_origin:
                raise SeeleError("ORIGIN_BLOCKED", "Origin does not match challenge", 403)
            self._items.pop(token, None)
            self._used[token] = now + self.ttl

    def _prune(self, now):
        self._prune_used(now)
        # Keep expired pending entries briefly so expiry and replay remain distinct.
        self._items = {key: value for key, value in self._items.items() if value[0] + self.ttl > now}

    def _prune_used(self, now):
        self._used = {key: expiry for key, expiry in self._used.items() if expiry > now}
