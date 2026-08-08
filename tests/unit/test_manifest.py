import copy
import json
import tempfile
import unittest
from pathlib import Path

from seele_blender.errors import SeeleError
from seele_blender.bridge.challenge import ChallengeStore
from seele_blender.transfer.manifest import validate_dcc_manifest, validate_direct_envelope, validate_gltf_dependencies


FIXTURES = Path(__file__).parents[1] / "fixtures"


def load(name="valid-minimal-fbx.json"):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class ManifestTests(unittest.TestCase):
    def validate(self, value, formats=("fbx", "gltf", "glb", "stl")):
        return validate_dcc_manifest(value, "fixture-receiver", formats, {"assets.example.com"})

    def test_valid_fbx_and_gltf(self):
        self.assertEqual(self.validate(load())["format"], "fbx")
        self.assertEqual(self.validate(load("valid-gltf-multifile.json"))["entryFilePath"], "model/scene.gltf")

    def test_invalid_contract_fixtures(self):
        for filename in (
            "invalid-path-traversal.json",
            "invalid-missing-entry.json",
            "invalid-unsupported-format.json",
            "invalid-over-limits.json",
            "invalid-blocked-host.json",
            "invalid-expired.json",
            "invalid-receiver-mismatch.json",
        ):
            rule = load(filename)
            value = load()
            target = value
            parts = rule["mutation"].split(".")
            for part in parts[:-1]:
                target = target[int(part)] if isinstance(target, list) else target[part]
            last = parts[-1]
            if isinstance(target, list):
                target[int(last)] = rule["value"]
            else:
                target[last] = rule["value"]
            with self.subTest(filename=filename), self.assertRaises(SeeleError) as raised:
                self.validate(value)
            self.assertEqual(raised.exception.code, rule["expectedCode"])

    def test_duplicate_file_id_and_path(self):
        value = load()
        value["files"].append(copy.deepcopy(value["files"][0]))
        with self.assertRaises(SeeleError) as raised:
            self.validate(value)
        self.assertEqual(raised.exception.code, "INVALID_MANIFEST")

    def test_receiver_and_expiry(self):
        value = load()
        value["receiverId"] = "other"
        with self.assertRaises(SeeleError) as raised:
            self.validate(value)
        self.assertEqual(raised.exception.code, "RECEIVER_MISMATCH")
        value = load()
        value["expiresAt"] = "2000-01-01T00:00:00Z"
        with self.assertRaises(SeeleError) as raised:
            self.validate(value)
        self.assertEqual(raised.exception.code, "TRANSFER_EXPIRED")

    def test_gltf_dependencies_must_be_declared(self):
        manifest = self.validate(load("valid-gltf-multifile.json"))
        with tempfile.TemporaryDirectory() as root:
            entry = Path(root) / "scene.gltf"
            entry.write_text('{"buffers":[{"uri":"missing.bin"}]}', encoding="utf-8")
            with self.assertRaises(SeeleError) as raised:
                validate_gltf_dependencies(manifest, {manifest["entryFilePath"]: str(entry)})
        self.assertEqual(raised.exception.code, "DEPENDENCY_MISSING")

    def test_direct_envelope_consumes_bound_challenge(self):
        store = ChallengeStore()
        token, _ = store.issue("fixture-receiver", "https://app.example.com")
        envelope = {
            "version": "dcc-transfer.v1",
            "receiverId": "fixture-receiver",
            "challenge": token,
            "manifest": load(),
        }
        result = validate_direct_envelope(
            envelope,
            "fixture-receiver",
            "https://app.example.com",
            store.consume,
            {"fbx"},
            {"assets.example.com"},
        )
        self.assertEqual(result["format"], "fbx")
        with self.assertRaises(SeeleError) as raised:
            validate_direct_envelope(envelope, "fixture-receiver", "https://app.example.com", store.consume, {"fbx"}, {"assets.example.com"})
        self.assertEqual(raised.exception.code, "CHALLENGE_REPLAYED")

    def test_integrity_metadata_is_optional_but_strict_when_present(self):
        value = load("valid-fbx-missing-integrity.json")
        result = self.validate(value)
        self.assertEqual(len(result["integrityWarnings"]), 2)
        self.assertIsNone(result["files"][0]["sha256"])
        self.assertIsNone(result["files"][0]["sizeBytes"])
        for field, invalid in (("sha256", "abc"), ("sizeBytes", "123")):
            value = load()
            value["files"][0][field] = invalid
            with self.subTest(field=field), self.assertRaises(SeeleError) as raised:
                self.validate(value)
            self.assertEqual(raised.exception.code, "INVALID_MANIFEST")


if __name__ == "__main__":
    unittest.main()
