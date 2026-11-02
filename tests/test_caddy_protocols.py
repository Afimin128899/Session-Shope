"""Preserve Caddy sites when disabling an optional conflicting UDP listener."""
import unittest
from deploy.caddy_protocols import configure, OPTIONS


class CaddyProtocolTests(unittest.TestCase):
    def test_default_package_config_preserved(self):
        old = '# Default site\n:80 {\n file_server\n}\nimport /etc/caddy/session-shope/*.caddy\n'
        self.assertEqual(configure(old), OPTIONS + old)

    def test_repeated_run_is_idempotent(self):
        old = 'sbandsub.space {\n reverse_proxy 127.0.0.1:8080\n}\n'
        self.assertEqual(configure(configure(old)), configure(old))

    def test_formatted_own_global_block_is_recognized(self):
        old = '# header\n{\n servers {\n protocols h1 h2\n }\n}\nexample.com {respond ok}\n'
        self.assertEqual(configure(old), old)

    def test_unknown_global_block_is_not_overwritten(self):
        with self.assertRaisesRegex(ValueError, 'глобальный блок'):
            configure('{\n email admin@example.com\n}\nexample.com {respond ok}\n')

    def test_http3_not_silently_retained(self):
        with self.assertRaises(ValueError):
            configure('{\n servers {\n protocols h1 h2 h3\n }\n}\n')
