import unittest
import tempfile
from pathlib import Path
from dotenv import dotenv_values
from deploy.connect_backup import repository, serialize
from deploy.backup_db import restic_command


class OffsiteConfigurationTests(unittest.TestCase):
    def test_s3_requires_https_without_embedded_credentials(self):
        self.assertEqual(repository('s3:https://storage.example/bucket/app','s3'),'s3:https://storage.example/bucket/app')
        for address in ['s3:http://storage.example/bucket','s3:https://user:pass@storage.example/bucket','s3:https://storage.example','s3:https://storage.example/bucket?secret=bad']:
            with self.assertRaises(ValueError): repository(address,'s3')

    def test_sftp_rejects_shell_options_and_control_characters(self):
        self.assertEqual(repository('sftp:backup@host.example:/backups/app','sftp'),'sftp:backup@host.example:/backups/app')
        for address in ['sftp:-oBad@host:/x','sftp:user@host:/x;command','sftp:user@host:/x\ncommand','sftp:user:password@host:/x']:
            with self.assertRaises(ValueError): repository(address,'sftp')

    def test_credential_round_trip_without_interpolation(self):
        values={'AWS_SECRET_ACCESS_KEY':'test${HOME}\\"key','RESTIC_REPOSITORY':'s3:https://host/bucket'}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'backup.env';path.write_text(serialize(values))
            self.assertEqual(dict(dotenv_values(path,interpolate=False)),values)

    def test_strict_sftp_command_reaches_every_restic_invocation(self):
        command='ssh -oBatchMode=yes -oStrictHostKeyChecking=yes backup@host -s sftp'
        self.assertEqual(restic_command({'RESTIC_SFTP_COMMAND':command}),['restic','-o','sftp.command='+command])
        self.assertEqual(restic_command({}),['restic'])
