"""Fresh-VPS configuration: no real tokens, network, MariaDB or /etc changes."""
import contextlib
import io
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from test_payments import config
from deploy import bootstrap_env as bootstrap
from dotenv import dotenv_values


class FreshBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / 'project'
        self.project.mkdir()
        self.state = Path(self.temp.name) / 'state'
        self.token = '123456:fake-token-only-for-tests'
        self.inputs = [self.token, '12345', 'a' * 32, '42']

    def create(self, sql_result=None):
        output = io.StringIO()
        with patch.object(bootstrap, 'mysql', side_effect=sql_result or ['0\n0', '']) as mysql, \
             patch.object(bootstrap, 'verify_bot'), \
             patch.object(bootstrap, 'read_value', side_effect=self.inputs), \
             contextlib.redirect_stdout(output):
            bootstrap.configure(self.project, self.state)
        return output.getvalue(), mysql.call_args_list

    def test_creates_private_config_without_printing_credentials(self):
        output, calls = self.create()
        values = dotenv_values(self.project / '.env')
        self.assertEqual(values['BOT_TOKEN'], self.token)
        self.assertEqual(values['DB_HOST'], '127.0.0.1')
        self.assertEqual(len(values['DB_PASSWORD']), 64)
        self.assertEqual(stat.S_IMODE((self.project / '.env').stat().st_mode), 0o600)
        self.assertNotIn(self.token, output)
        self.assertNotIn(values['DB_PASSWORD'], output)
        self.assertIn('CREATE DATABASE IF NOT EXISTS', calls[1].args[0])
        self.assertNotIn('DROP', calls[1].args[0])

    def test_existing_checkout_env_is_backed_up_privately(self):
        (self.project / '.env').write_text('OLD_VALUE=keep\n')
        self.create()
        backup = self.state / 'env-before-bootstrap'
        self.assertEqual(backup.read_text(), 'OLD_VALUE=keep\n')
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)

    def test_retry_reuses_password_and_does_not_prompt_again(self):
        self.create()
        original = (self.project / '.env').read_bytes()
        with patch.object(bootstrap, 'mysql', return_value='') as mysql, \
             patch.object(bootstrap, 'verify_bot'), \
             patch.object(bootstrap, 'read_value') as prompt, \
             contextlib.redirect_stdout(io.StringIO()):
            bootstrap.configure(self.project, self.state)
        prompt.assert_not_called()
        mysql.assert_called_once()
        self.assertEqual((self.project / '.env').read_bytes(), original)

    def test_existing_database_is_never_taken_over(self):
        with patch.object(bootstrap, 'mysql', return_value='1\n0'), \
             patch.object(bootstrap, 'read_value') as prompt:
            with self.assertRaisesRegex(ValueError, 'уже существуют'):
                bootstrap.configure(self.project, self.state)
        prompt.assert_not_called()
        self.assertFalse((self.project / '.env').exists())

    def test_provisioning_failure_retains_credentials_for_retry(self):
        with self.assertRaisesRegex(ValueError, 'fixture failure'):
            self.create(['0\n0', ValueError('fixture failure')])
        self.assertTrue((self.project / '.env').exists())
        self.assertTrue((self.state / 'managed-env').exists())

    def test_foreign_project_marker_is_rejected(self):
        self.state.mkdir()
        (self.state / 'managed-env').write_text('/another/project')
        with self.assertRaisesRegex(ValueError, 'другому каталогу'), patch.object(bootstrap, 'mysql') as mysql:
            bootstrap.configure(self.project, self.state)
        mysql.assert_not_called()

    def test_telegram_error_does_not_print_token_url(self):
        error = urllib.error.HTTPError('https://api.telegram.org/bot' + self.token, 401, 'Unauthorized', {}, None)
        with patch.object(bootstrap.urllib.request, 'urlopen', side_effect=error):
            with self.assertRaises(ValueError) as caught:
                bootstrap.verify_bot(self.token)
        self.assertIn('401', str(caught.exception))
        self.assertNotIn(self.token, str(caught.exception))

    def test_invalid_hidden_input_is_rejected_without_echoing(self):
        with patch.object(bootstrap.getpass, 'getpass', return_value='invalid-secret'):
            with self.assertRaises(ValueError) as caught:
                bootstrap.read_value('Secret: ', '[0-9]+', hidden=True)
        self.assertNotIn('invalid-secret', str(caught.exception))
