import unittest

from seele_blender.bridge.challenge import ChallengeStore
from seele_blender.bridge.cors import allowed_origins, is_origin_allowed
from seele_blender.errors import SeeleError


class SecurityTests(unittest.TestCase):
    def test_exact_origin_only(self):
        allowed = allowed_origins("https://app.example.com")
        self.assertTrue(is_origin_allowed("https://app.example.com", allowed))
        self.assertFalse(is_origin_allowed("https://app.example.com.evil.test", allowed))
        self.assertFalse(is_origin_allowed("https://app.example.com:444", allowed))

    def test_development_origin_requires_switch(self):
        disabled = allowed_origins("https://app.example.com", "http://localhost:3000", False)
        enabled = allowed_origins("https://app.example.com", "http://localhost:3000", True)
        self.assertFalse(is_origin_allowed("http://localhost:3000", disabled))
        self.assertTrue(is_origin_allowed("http://localhost:3000", enabled))

    def test_challenge_is_one_time(self):
        store = ChallengeStore(ttl=60)
        token, _ = store.issue("receiver", "https://app.example.com")
        store.consume(token, "receiver", "https://app.example.com")
        with self.assertRaises(SeeleError) as raised:
            store.consume(token, "receiver", "https://app.example.com")
        self.assertEqual(raised.exception.code, "CHALLENGE_REPLAYED")

    def test_challenge_is_bound_to_receiver_and_origin(self):
        store = ChallengeStore(ttl=60)
        token, _ = store.issue("receiver", "https://app.example.com")
        with self.assertRaises(SeeleError) as raised:
            store.consume(token, "other", "https://app.example.com")
        self.assertEqual(raised.exception.code, "RECEIVER_MISMATCH")
        with self.assertRaises(SeeleError) as raised:
            store.consume(token, "receiver", "https://other.example.com")
        self.assertEqual(raised.exception.code, "ORIGIN_BLOCKED")

    def test_expired_challenge_has_distinct_code(self):
        store = ChallengeStore(ttl=-1)
        token, _ = store.issue("receiver", "https://app.example.com")
        with self.assertRaises(SeeleError) as raised:
            store.consume(token, "receiver", "https://app.example.com")
        self.assertEqual(raised.exception.code, "CHALLENGE_EXPIRED")


if __name__ == "__main__":
    unittest.main()
