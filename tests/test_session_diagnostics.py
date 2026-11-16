"""Synthetic auth keys only; no Telegram or database connection."""
import base64
import ipaddress
import json
import struct
import unittest
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

from services.session_diagnostics import inspect_session, report_batches, send_report


def session(key=b'k' * 256, address='149.154.167.51', dc=2, port=443):
    ip = ipaddress.ip_address(address).packed
    return '1' + base64.urlsafe_b64encode(struct.pack(f'>B{len(ip)}sH256s', dc, ip, port, key)).decode()


class FormatTests(unittest.TestCase):
    def test_valid_ipv4_and_ipv6(self):
        self.assertEqual(inspect_session(session())[0], 'format_ok')
        # Same allowlist as SQLite imports: IPv6 currently has no allowed ranges.
        self.assertEqual(inspect_session(session(address='2001:db8::1'))[0], 'invalid_endpoint')

    def test_missing_and_wrong_types(self):
        for value in (None, ''):
            self.assertEqual(inspect_session(value), ('missing', None))
        for value in (12, b'abc', {}, 'short', '1' + '!' * 352):
            self.assertEqual(inspect_session(value), ('invalid_format', None))

    def test_version_and_zero_key(self):
        self.assertEqual(inspect_session('2' + session()[1:])[0], 'unsupported_version')
        self.assertEqual(inspect_session(session(key=bytes(256))), ('empty_auth_key', None))

    def test_endpoint_validation(self):
        for value in (session(address='127.0.0.1'), session(dc=0), session(port=22)):
            self.assertEqual(inspect_session(value), ('invalid_endpoint', None))

    def test_fingerprint_uses_key_instead_of_session_encoding(self):
        self.assertEqual(inspect_session(session())[1], inspect_session(session(port=80))[1])
        self.assertNotEqual(inspect_session(session())[1], inspect_session(session(key=b'z' * 256))[1])


class ReportTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_across_batches_and_no_credentials(self):
        secret = session()
        fetch = AsyncMock(side_effect=[ [{'maximum': 3}],
            [{'id': 1, 'data': secret}],
            [{'id': 2, 'data': session(port=80)}, {'id': 3, 'data': ''}] ])
        reports = [part async for part in report_batches(fetch)]
        self.assertEqual(reports[1]['items'][0], {'account_id': 2, 'status': 'duplicate_key', 'duplicate_of': 1})
        self.assertEqual(reports[1]['cumulative_counts'], {'format_ok': 1, 'duplicate_key': 1, 'missing': 1})
        encoded = json.dumps(reports)
        for private in (secret, 'auth_key', 'password', 'fingerprint', '149.154'):
            self.assertNotIn(private, encoded)
        self.assertFalse(reports[0]['telegram_checked'])
        self.assertEqual(fetch.call_args_list[2].args[1], (1, 3))
        for call in fetch.call_args_list:
            self.assertTrue(call.args[0].startswith('SELECT '))
            if 'data' in call.args[0]:
                self.assertIn("status IN ('available','review')", call.args[0])
                self.assertIn('LIMIT 500', call.args[0])

    async def test_empty_inventory_still_produces_report(self):
        fetch = AsyncMock(return_value=[{'maximum': 0}])
        parts = [part async for part in report_batches(fetch)]
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0]['items'], [])
        self.assertEqual(fetch.await_count, 1)

    async def test_inventory_removed_after_snapshot(self):
        fetch = AsyncMock(side_effect=[[{'maximum': 2}], []])
        parts = [part async for part in report_batches(fetch)]
        self.assertEqual(parts[0]['cumulative_counts'], {})

    async def test_delivery_uses_requested_admin_and_sanitized_json(self):
        types = ModuleType('aiogram.types')
        types.BufferedInputFile = lambda data, filename: SimpleNamespace(data=data, filename=filename)
        database = ModuleType('database.admin_web')
        database.rows = AsyncMock(side_effect=[[{'maximum': 1}], [{'id': 1, 'data': session()}]])
        bot = SimpleNamespace(send_document=AsyncMock())
        with patch.dict(sys.modules, {'aiogram.types': types, 'database.admin_web': database}):
            await send_report(bot, 42)
        bot.send_document.assert_awaited_once()
        recipient, document = bot.send_document.call_args.args
        self.assertEqual(recipient, 42)
        self.assertTrue(document.filename.endswith('.json'))
        self.assertEqual(json.loads(document.data)['items'], [{'account_id': 1, 'status': 'format_ok'}])
        self.assertNotIn(session().encode(), document.data)
