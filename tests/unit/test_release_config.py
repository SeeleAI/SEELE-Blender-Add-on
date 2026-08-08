import unittest

from seele_blender import release_config


class ReleaseConfigTests(unittest.TestCase):
    def test_public_source_defaults_are_exact(self):
        self.assertEqual(release_config.BUILD_CHANNEL, "public")
        self.assertEqual(release_config.DEFAULT_PRODUCTION_ORIGIN, "https://www.seeles.ai")
        self.assertEqual(release_config.DEFAULT_BRIDGE_PORT, 9878)
        self.assertEqual(
            release_config.DEFAULT_DOWNLOAD_HOSTS,
            (
                "static.seeles.ai",
                "agent-workspace-1368252780.cos.na-ashburn.myqcloud.com",
            ),
        )
        self.assertNotIn("*.seeles.ai", release_config.DEFAULT_DOWNLOAD_HOSTS)
        self.assertNotIn("*.myqcloud.com", release_config.DEFAULT_DOWNLOAD_HOSTS)


if __name__ == "__main__":
    unittest.main()
