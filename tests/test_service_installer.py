"""Exercise service updates without writing to /etc or starting services."""
import contextlib
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from deploy import create_service as installer


class ServiceInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'project with space'
        (self.root / 'miniapp').mkdir(parents=True)
        (self.root / 'deploy').mkdir()
        (self.root / 'bot.py').touch()
        (self.root / 'miniapp/server.py').touch()
        self.base = '[Service]\nEnvironment="MINIAPP_URL=https://sbandsub.space"\n'
        (self.root / 'deploy/miniapp-systemd.conf').write_text(self.base)
        self.config = Path(self.temp.name) / 'systemd'
        self.config.mkdir()
        self.python = Path(self.temp.name) / 'python'
        self.python.touch()
        self.destination = self.config / 'shop.service.d/miniapp.conf'

    def invoke(self):
        def local_path(value):
            return self.config if str(value) == '/etc/systemd/system' else Path(value)
        def command(*args):
            return 'loaded' if args[:2] == ('systemctl', 'show') else ''
        with patch.object(installer, 'ROOT', self.root), \
             patch.object(installer, 'Path', side_effect=local_path), \
             patch.object(installer, 'discover_service', return_value='shop.service'), \
             patch.object(installer.os, 'geteuid', return_value=0), \
             patch.object(installer.subprocess, 'run', return_value=SimpleNamespace(returncode=0)), \
             patch.object(installer, 'run', side_effect=command) as run, \
             patch('sys.argv', ['create_service.py', '--python', str(self.python)]), \
             contextlib.redirect_stdout(io.StringIO()):
            installer.main()
            return run.call_args_list

    def test_existing_service_switches_to_installed_venv(self):
        calls = self.invoke()
        text = self.destination.read_text()
        self.assertIn(f'ExecStart="{self.python}" "{self.root / "bot.py"}"', text)
        self.assertIn(f'WorkingDirectory={self.root}', text)
        self.assertIn('ExecStart=\n', text)
        self.assertTrue(any(c.args == ('systemctl', 'restart', 'shop.service') for c in calls))

    def test_known_old_dropin_can_be_upgraded_and_rerun(self):
        self.destination.parent.mkdir()
        self.destination.write_text(self.base)
        self.invoke()
        first = self.destination.read_bytes()
        self.invoke()
        self.assertEqual(self.destination.read_bytes(), first)

    def test_custom_configuration_is_preserved(self):
        self.destination.parent.mkdir()
        self.destination.write_text('[Service]\nEnvironment="CUSTOM_SETTING=keep"\n')
        with self.assertRaisesRegex(ValueError, 'оставлен без изменений'):
            self.invoke()
        self.assertIn('CUSTOM_SETTING=keep', self.destination.read_text())
