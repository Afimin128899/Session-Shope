"""Backup credential hygiene, schedules and repository isolation."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from deploy.backup_db import client_options, config, latest
from deploy.setup_backups import units, save_unit


class BackupTests(unittest.TestCase):
    def test_database_password_is_quoted_not_interpreted(self):
        result = client_options({'DB_HOST': '127.0.0.1', 'DB_USER': 'app', 'DB_PASSWORD': 'a"b\\c', 'DB_PORT': '3306'})
        self.assertIn('password="a\\"b\\\\c"', result)
        with self.assertRaises(ValueError):
            client_options({'DB_HOST': 'x\nuser=root', 'DB_USER': 'app', 'DB_PASSWORD': 'secret'})

    def test_remote_database_keeps_tls_verification(self):
        result = client_options({'DB_HOST': 'db.example.com', 'DB_USER': 'app', 'DB_PASSWORD': 'test'})
        self.assertIn('ssl=1', result)
        self.assertIn('ssl-verify-server-cert=1', result)
        self.assertNotIn('ssl=0', result)

    def test_local_socket_is_explicit_and_not_used_for_remote_host(self):
        settings = {'DB_HOST': '127.0.0.1', 'DB_USER': 'app', 'DB_PASSWORD': 'test', 'DB_SOCKET': '/run/mysqld/mysqld.sock'}
        self.assertIn('protocol=socket', client_options(settings))
        with self.assertRaises(ValueError):
            client_options(settings | {'DB_HOST': 'remote.example.com'})

    def test_key_must_be_private(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env').write_text('DB_HOST=127.0.0.1\nDB_USER=app\nDB_PASSWORD=test\nDB_NAME=shop\n')
            key = root / 'key'; key.write_text('fixture-key'); key.chmod(0o644)
            with patch.dict(os.environ, RESTIC_REPOSITORY=str(root / 'repo'), RESTIC_PASSWORD_FILE=str(key)):
                with self.assertRaisesRegex(ValueError, '600'):
                    config(root)
                key.chmod(0o600)
                values, env = config(root)
                self.assertEqual(values['DB_NAME'], 'shop')
                self.assertEqual(env['RESTIC_PASSWORD_FILE'], str(key))

    def test_snapshot_id_is_validated_before_restore(self):
        with patch('deploy.backup_db.restic', return_value='[{"id":"../../bad","time":"2026"}]'):
            with self.assertRaises(ValueError): latest({})

    def test_daily_and_weekly_jobs_use_moscow_and_separate_verification(self):
        result = units(Path('/opt/Session Shope'), Path('/opt/venv/bin/python'))
        self.assertIn('04:00:00 Europe/Moscow', result['session-shope-backup.timer'])
        self.assertIn('Sun *-*-* 05:00:00 Europe/Moscow', result['session-shope-backup-check.timer'])
        self.assertIn('verify --project', result['session-shope-backup-check.service'])
        self.assertIn('Persistent=true', result['session-shope-backup.timer'])
        self.assertNotIn('DB_PASSWORD', str(result))

    def test_external_database_uses_repository_check_without_root_restore(self):
        result = units(Path('/opt/shop'), Path('/opt/venv/bin/python'), local=False)
        self.assertIn('check --project', result['session-shope-backup-check.service'])

    def test_custom_systemd_unit_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'backup.service'
            target.write_text('user-config')
            with self.assertRaises(ValueError): save_unit(target, '# Managed\n[Unit]\n')
            self.assertEqual(target.read_text(), 'user-config')
