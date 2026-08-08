import unittest

from seele_blender.errors import SeeleError
from seele_blender.transfer.manifest import DCC_PROTOCOL
from seele_blender.transfer.state import TransferStateStore


TRANSFER_ID = "11111111-1111-4111-8111-111111111111"


class StateTests(unittest.TestCase):
    def test_happy_path(self):
        store = TransferStateStore()
        store.create(TRANSFER_ID, DCC_PROTOCOL)
        for state in ("downloading", "verifying", "queued", "importing_geometry", "importing_materials", "completed"):
            store.update(TRANSFER_ID, state=state)
        self.assertEqual(store.get(TRANSFER_ID)["state"], "completed")

    def test_illegal_transition_and_terminal_cannot_revive(self):
        store = TransferStateStore()
        store.create(TRANSFER_ID, DCC_PROTOCOL)
        with self.assertRaises(SeeleError):
            store.update(TRANSFER_ID, state="completed")
        store.request_cancel(TRANSFER_ID)
        with self.assertRaises(SeeleError):
            store.update(TRANSFER_ID, state="downloading")

    def test_cancel_is_idempotent_and_pending_during_import(self):
        store = TransferStateStore()
        store.create(TRANSFER_ID, DCC_PROTOCOL)
        for state in ("downloading", "verifying", "queued", "importing_geometry"):
            store.update(TRANSFER_ID, state=state)
        first = store.request_cancel(TRANSFER_ID)
        second = store.request_cancel(TRANSFER_ID)
        self.assertEqual(first["state"], "cancel_pending")
        self.assertEqual(second["state"], "cancel_pending")
        self.assertEqual(store.finish_cancel(TRANSFER_ID)["state"], "cancelled")

    def test_duplicate_transfer_conflicts(self):
        store = TransferStateStore()
        store.create(TRANSFER_ID, DCC_PROTOCOL)
        with self.assertRaises(SeeleError) as raised:
            store.create(TRANSFER_ID, DCC_PROTOCOL)
        self.assertEqual(raised.exception.code, "TRANSFER_CONFLICT")

    def test_import_retry_creates_new_attempt_without_exposing_private_data(self):
        store = TransferStateStore()
        store.create(TRANSFER_ID, DCC_PROTOCOL, manifest={"secret": "download-url"})
        store.update(TRANSFER_ID, state="downloading")
        store.update(TRANSFER_ID, state="verifying")
        store.update(TRANSFER_ID, state="queued", localFiles={"model": "C:/private/model.fbx"})
        store.update(TRANSFER_ID, state="importing_geometry")
        store.fail(TRANSFER_ID, SeeleError("IMPORT_GEOMETRY_FAILED", "Import failed", 500, True, "geometry"))
        retried = store.begin_import_retry(TRANSFER_ID)
        self.assertEqual(retried["state"], "queued")
        self.assertEqual(retried["attempt"], 2)
        public = store.get(TRANSFER_ID)
        self.assertNotIn("manifest", public)
        self.assertNotIn("localFiles", public)

    def test_download_failure_never_allows_import_retry(self):
        store = TransferStateStore()
        store.create(TRANSFER_ID, DCC_PROTOCOL, manifest={"files": []})
        store.update(TRANSFER_ID, state="downloading")
        failed = store.fail(TRANSFER_ID, SeeleError("DOWNLOAD_TIMEOUT", "Download timed out", 504, True, "downloading"))
        self.assertFalse(failed["canRetryImport"])
        with self.assertRaises(SeeleError):
            store.begin_import_retry(TRANSFER_ID)


if __name__ == "__main__":
    unittest.main()
