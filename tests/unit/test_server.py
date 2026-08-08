import json
import tempfile
import unittest
import urllib.error
import urllib.request

from seele_blender import runtime
from seele_blender.bridge.server import RuntimeConfig, start, stop


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.cache = tempfile.TemporaryDirectory()
        config = RuntimeConfig(
            port=0,
            cache_dir=self.cache.name,
            download_hosts=("assets.example.com",),
            allowed_origins=frozenset({"https://app.example.com"}),
            receiver_id="receiver",
            addon_version="0.2.0",
            blender_version="4.0.0",
            formats=("fbx",),
            importer_readiness=(("fbx", True), ("gltf", False)),
        )
        self.server = start(config)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        stop()
        runtime.reset()
        self.cache.cleanup()

    def request(self, path, origin="https://app.example.com", method="GET"):
        request = urllib.request.Request(self.url + path, method=method, headers={"Origin": origin})
        return urllib.request.urlopen(request, timeout=2)

    def test_health_and_local_binding(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        with self.request("/v1/health") as response:
            payload = json.loads(response.read())
        self.assertTrue(payload["ok"])
        data = payload["data"]
        self.assertEqual(data["service"], "seele-dcc-receiver")
        self.assertEqual(data["protocols"], ["dcc-transfer.v1"])
        self.assertEqual(data["capabilities"]["formats"], ["fbx"])
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "https://app.example.com")
        self.assertTrue(data["challenge"])
        self.assertTrue(data["challengeExpiresAt"])

    def test_rejects_unlisted_origin(self):
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.request("/v1/health", origin="https://evil.example")
        self.assertEqual(raised.exception.code, 403)
        payload = json.loads(raised.exception.read())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "ORIGIN_BLOCKED")
        self.assertIn("retryable", payload["error"])
        self.assertIn("stage", payload["error"])


if __name__ == "__main__":
    unittest.main()
