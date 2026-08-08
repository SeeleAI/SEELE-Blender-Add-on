"""Deprecated 0.2.x legacy Consume client; removal is scheduled for 0.3.0."""

import json
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlparse

from ..errors import SeeleError


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SeeleError("DOWNLOAD_HOST_BLOCKED", "Legacy authorization redirect is not allowed", 502, False, "accepted")


def consume_transfer(consume_url, envelope, timeout=30):
    parsed = urlparse(consume_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise SeeleError("INVALID_REQUEST", "A valid legacy HTTPS consume URL is required")
    body = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        consume_url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    opener = urllib.request.build_opener(
        NoRedirectHandler(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.status < 200 or response.status >= 300:
                raise SeeleError("TRANSFER_EXPIRED", "Legacy transfer authorization was rejected", 401)
            encoded = response.read(4 * 1024 * 1024 + 1)
            if len(encoded) > 4 * 1024 * 1024:
                raise SeeleError("INVALID_MANIFEST", "Authorization response is too large")
            payload = json.loads(encoded.decode("utf-8"))
    except SeeleError:
        raise
    except urllib.error.HTTPError as exc:
        code = "TRANSFER_EXPIRED" if exc.code in {401, 403, 404, 410} else "INTERNAL_ERROR"
        raise SeeleError(code, "Transfer authorization failed", exc.code) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SeeleError("INTERNAL_ERROR", "Legacy authorization service is unavailable", 502, True, "accepted") from exc
    manifest = payload.get("manifest") if isinstance(payload, dict) and "manifest" in payload else payload
    if not isinstance(manifest, dict):
        raise SeeleError("INVALID_MANIFEST", "Authorization response has no manifest")
    return manifest
