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


class ServiceDiscoveryTests(unittest.TestCase):
    root = Path('/opt/session-shope')

    def command(self, listing, units):
        def run(*args):
            if args[1] == 'list-unit-files':
                return listing
            name, prop = args[2], args[3]
            unit = units[name]
            if isinstance(unit, Exception):
                raise unit
            return unit.get(prop, '')
        return run

    def unit(self, name, bot=False):
        return {'--property=LoadState': 'loaded', '--property=Id': name,
                '--property=ExecStart': '/usr/bin/python3 /opt/session-shope/bot.py' if bot else '/usr/bin/other',
                '--property=WorkingDirectory': str(self.root) if bot else '/'}

    def test_ubuntu_templates_and_masked_units_are_not_inspected(self):
        listing = 'getty@.service indirect enabled\nmasked.service masked enabled\nssh.service enabled enabled\n'
        with patch.object(installer, 'run', side_effect=self.command(listing, {'ssh.service': self.unit('ssh.service')})) as run:
            self.assertIsNone(installer.discover_service(self.root))
            self.assertFalse(any('getty@.service' in c.args or 'masked.service' in c.args for c in run.call_args_list if c.args[1] == 'show'))

    def test_unavailable_individual_unit_does_not_break_fresh_install(self):
        import subprocess
        units = {'gone.service': subprocess.CalledProcessError(1, ['systemctl']), 'ssh.service': self.unit('ssh.service')}
        with patch.object(installer, 'run', side_effect=self.command('gone.service alias\nssh.service enabled', units)):
            self.assertIsNone(installer.discover_service(self.root))

    def test_alias_and_actual_service_count_as_one(self):
        units = {'alias.service': self.unit('shop.service', True), 'shop.service': self.unit('shop.service', True)}
        with patch.object(installer, 'run', side_effect=self.command('alias.service alias\nshop.service enabled', units)):
            self.assertEqual(installer.discover_service(self.root), 'shop.service')

    def test_two_real_bot_services_require_explicit_selection(self):
        units = {'one.service': self.unit('one.service', True), 'two.service': self.unit('two.service', True)}
        with patch.object(installer, 'run', side_effect=self.command('one.service enabled\ntwo.service enabled', units)):
            with self.assertRaisesRegex(ValueError, 'несколько сервисов'):
                installer.discover_service(self.root)

    def test_global_systemd_failure_is_not_treated_as_no_existing_bot(self):
        import subprocess
        units = {'ssh.service': subprocess.CalledProcessError(1, ['systemctl'])}
        with patch.object(installer, 'run', side_effect=self.command('ssh.service enabled', units)):
            with self.assertRaisesRegex(ValueError, 'не смог прочитать'):
                installer.discover_service(self.root)
