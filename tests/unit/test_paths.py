import tempfile
import unittest
import uuid
from pathlib import Path

from seele_blender.errors import SeeleError
from seele_blender.transfer.paths import (
    SENTINEL,
    clear_cache,
    ensure_cache_root,
    resolve_cache_path,
    safe_relative_path,
    transfer_dir,
    validate_cache_root,
)


class PathTests(unittest.TestCase):
    def test_accepts_nested_relative_path(self):
        self.assertEqual(safe_relative_path("model/textures/a.png").as_posix(), "model/textures/a.png")

    def test_rejects_escape_and_absolute_paths(self):
        for value in ("../secret", "/tmp/a", "C:\\temp\\a", "model/../../a", "a//b", "CON/file", "encoded/%2e%2e/file", ""):
            with self.subTest(value=value), self.assertRaises(SeeleError):
                safe_relative_path(value)

    def test_resolve_stays_under_root(self):
        with tempfile.TemporaryDirectory() as root:
            result = resolve_cache_path(root, "a/b.glb")
            result.relative_to(Path(root).resolve())

    def test_managed_cache_requires_sentinel_and_only_clears_transfer_dirs(self):
        with tempfile.TemporaryDirectory() as parent:
            root = ensure_cache_root(Path(parent) / "cache")
            transfer = root / str(uuid.uuid4())
            transfer.mkdir()
            (transfer / "file.bin").write_bytes(b"x")
            unrelated = root / "keep.txt"
            unrelated.write_text("keep", encoding="utf-8")
            clear_cache(root)
            self.assertFalse(transfer.exists())
            self.assertTrue(unrelated.exists())
            self.assertTrue((root / SENTINEL).exists())

    def test_clear_rejects_unmanaged_and_dangerous_roots(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(SeeleError):
                clear_cache(root)
        with self.assertRaises(SeeleError):
            validate_cache_root(Path.home())

    def test_transfer_instances_are_isolated(self):
        with tempfile.TemporaryDirectory() as parent:
            root = ensure_cache_root(Path(parent) / "cache")
            transfer_id = str(uuid.uuid4())
            first = transfer_dir(root, transfer_id, str(uuid.uuid4()), create=True)
            second = transfer_dir(root, transfer_id, str(uuid.uuid4()), create=True)
            self.assertNotEqual(first, second)
            self.assertEqual(first.parent, second.parent)


if __name__ == "__main__":
    unittest.main()
