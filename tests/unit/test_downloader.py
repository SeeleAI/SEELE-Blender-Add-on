import hashlib
import json
import tempfile
import unittest
import uuid
import ssl
import urllib.error
from pathlib import Path
from unittest import mock

from seele_blender.errors import SeeleError
from seele_blender.transfer.downloader import SafeRedirectHandler, download_manifest
from seele_blender.transfer.manifest import validate_dcc_manifest
from seele_blender.transfer.paths import ensure_cache_root


FIXTURE = Path(__file__).parents[1] / "fixtures" / "valid-minimal-fbx.json"


class FakeResponse:
    status = 200

    def __init__(self, content, url="https://assets.example.com/file"):
        self.content = content
        self.url = url
        self.offset = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def geturl(self):
        return self.url

    def read(self, size=-1):
        if self.offset >= len(self.content):
            return b""
        result = self.content[self.offset:self.offset + size]
        self.offset += len(result)
        return result


class DownloaderTests(unittest.TestCase):
    def manifest(self, content):
        value = json.loads(FIXTURE.read_text(encoding="utf-8"))
        value["files"][0]["sizeBytes"] = len(content)
        value["files"][0]["sha256"] = hashlib.sha256(content).hexdigest()
        return validate_dcc_manifest(value, "fixture-receiver", {"fbx"}, {"assets.example.com"})

    def test_download_hash_mismatch(self):
        manifest = self.manifest(b"expected")
        opener = mock.Mock()
        opener.open.return_value = FakeResponse(b"tampered")
        with tempfile.TemporaryDirectory() as parent:
            root = ensure_cache_root(Path(parent) / "cache")
            with mock.patch("urllib.request.build_opener", return_value=opener):
                with self.assertRaises(SeeleError) as raised:
                    download_manifest(manifest, root, str(uuid.uuid4()), {"assets.example.com"}, lambda: False)
        self.assertIn(raised.exception.code, {"DOWNLOAD_SIZE_MISMATCH", "DOWNLOAD_HASH_MISMATCH"})

    def test_blocked_redirect(self):
        manifest = self.manifest(b"x")
        handler = SafeRedirectHandler({"assets.example.com"}, manifest)
        with self.assertRaises(SeeleError) as raised:
            handler.redirect_request(None, None, 302, "", {}, "https://evil.example/file")
        self.assertEqual(raised.exception.code, "DOWNLOAD_HOST_BLOCKED")

    def test_missing_hash_and_size_can_download_with_hard_limits(self):
        content = b"legacy-compatible"
        value = json.loads(FIXTURE.read_text(encoding="utf-8"))
        value["files"][0].pop("sha256")
        value["files"][0].pop("sizeBytes")
        manifest = validate_dcc_manifest(value, "fixture-receiver", {"fbx"}, {"assets.example.com"})
        opener = mock.Mock()
        opener.open.return_value = FakeResponse(content)
        with tempfile.TemporaryDirectory() as parent:
            root = ensure_cache_root(Path(parent) / "cache")
            with mock.patch("urllib.request.build_opener", return_value=opener):
                files = download_manifest(manifest, root, str(uuid.uuid4()), {"assets.example.com"}, lambda: False)
            self.assertEqual(Path(files["character.fbx"]).read_bytes(), content)

    def assert_open_error(self, side_effect, expected_code):
        manifest = self.manifest(b"x")
        opener = mock.Mock()
        opener.open.side_effect = side_effect
        with tempfile.TemporaryDirectory() as parent:
            root = ensure_cache_root(Path(parent) / "cache")
            with mock.patch("urllib.request.build_opener", return_value=opener):
                with self.assertRaises(SeeleError) as raised:
                    download_manifest(manifest, root, str(uuid.uuid4()), {"assets.example.com"}, lambda: False)
        self.assertEqual(raised.exception.code, expected_code)

    def test_http_auth_failure_is_download_expired(self):
        self.assert_open_error(
            urllib.error.HTTPError("https://redacted.invalid", 403, "Forbidden", {}, None),
            "DOWNLOAD_EXPIRED",
        )

    def test_tls_and_timeout_are_distinct(self):
        self.assert_open_error(
            urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate verify failed")),
            "DOWNLOAD_TLS_ERROR",
        )
        self.assert_open_error(TimeoutError(), "DOWNLOAD_TIMEOUT")


if __name__ == "__main__":
    unittest.main()
