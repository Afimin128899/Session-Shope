"""Provisioning check on our disposable MariaDB container, never production.

Prerequisites: MariaDB container session-shope-bootstrap-test and app image
session-shope-miniapp-test. The client shares the DB network namespace so
connections originate from localhost, exactly as on the native VPS.
Bot verification/input are replaced with test fixtures; SQL is real MariaDB.
"""
import asyncio
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy import bootstrap_env as bootstrap
from dotenv import dotenv_values


async def main():
    docker = ['docker', '--host=unix:///var/run/docker.sock', 'exec', '-i',
              'session-shope-bootstrap-test', 'mariadb', '--protocol=socket', '--batch', '--skip-column-names']
    def local_mysql(sql):
        result = subprocess.run(docker, input=sql, text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError('Disposable MariaDB SQL failed')
        return result.stdout.strip()
    with tempfile.TemporaryDirectory(prefix='session-bootstrap-test-') as temporary:
        root = Path(temporary)
        project = root / 'project'
        project.mkdir()
        state = root / 'state'
        with patch.object(bootstrap, 'mysql', side_effect=local_mysql), \
             patch.object(bootstrap, 'verify_bot'), \
             patch.object(bootstrap, 'read_value', side_effect=['123456:fake-test-token-not-real', '12345', 'a' * 32, '42']), \
             contextlib.redirect_stdout(io.StringIO()):
            bootstrap.configure(project, state)
        values = dotenv_values(project / '.env')
        original = (project / '.env').read_bytes()
        print('PASS: database and localhost application users created on MariaDB 10.11')
        client_code = """
import asyncio,json,sys
sys.path[:0]=['/source/tests','/source']
from test_payments import db
values=json.load(sys.stdin)
db.DB_CONFIG=dict(host='127.0.0.1',port=3306,user=values['DB_USER'],password=values['DB_PASSWORD'],db=values['DB_NAME'],autocommit=True)
async def main():
    try:
        await db.init_db()
        await db.create_user(42,'bootstrap_fixture')
        assert (await db.get_user(42))['id']==42
    finally:
        if db.pool:
            db.pool.close()
            await db.pool.wait_closed()
asyncio.run(main())
"""
        def verify_application():
            command=['docker','--host=unix:///var/run/docker.sock','run','--rm','-i','--user','0',
                     '--network','container:session-shope-bootstrap-test',
                     '--mount',f'type=bind,src={Path(__file__).resolve().parents[1]},dst=/source,readonly',
                     'session-shope-miniapp-test','python','-c',client_code]
            result=subprocess.run(command,input=json.dumps(dict(values)),text=True,capture_output=True)
            if result.returncode:
                raise RuntimeError('Application schema check failed in disposable container')
        verify_application()
        print('PASS: generated application account can initialize and use the full bot schema')
        with patch.object(bootstrap, 'mysql', side_effect=local_mysql), \
             patch.object(bootstrap, 'verify_bot'), \
             patch.object(bootstrap, 'read_value') as prompt, \
             contextlib.redirect_stdout(io.StringIO()):
            bootstrap.configure(project, state)
        prompt.assert_not_called()
        assert (project / '.env').read_bytes() == original
        verify_application()
        print('PASS: retry preserves credentials and existing database rows')
        print('All 3 fresh-bootstrap MariaDB scenarios passed.')


if __name__ == '__main__':
    asyncio.run(main())
