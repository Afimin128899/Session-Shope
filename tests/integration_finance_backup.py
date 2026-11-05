"""Run inside the disposable finance/backup test container, never on production.

Requires MariaDB on localhost and its Unix socket, plus restic and mariadb-client.
Credentials, schema and backup repositories are temporary fixtures.
"""
import asyncio
from decimal import Decimal
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
from uuid import uuid4

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
from test_payments import db
import aiomysql
from database import refunds, tickets
from miniapp.storage import checkout
from deploy import backup_db


async def main():
    checks = []
    def report(message):
        checks.append(message)
        print('PASS: ' + message, flush=True)
    name = 'finance_fixture_' + uuid4().hex
    db.DB_CONFIG = dict(host='127.0.0.1', port=3306, user='root', password='', db=name, autocommit=True)
    connection = await aiomysql.connect(host='127.0.0.1', user='root', password='', autocommit=True)
    try:
        await db.init_db()
        async with connection.cursor() as cur:
            await cur.execute(f'USE `{name}`')
            await cur.execute('INSERT INTO users (id,balance,balance_usdt) VALUES (42,1000,0),(43,0,0),(44,100,0)')
            await cur.execute('INSERT INTO referrals (referral_id,referrer_id) VALUES (42,43)')
            await cur.execute('UPDATE referral_settings SET discount_pct=5,bonus_pct=5 WHERE id=1')
            await cur.execute("INSERT INTO accounts (country,number,password,price,data) VALUES ('us','+15551234567','fixture-password',19.99,'PRIVATE_SESSION_FIXTURE')")
            account = cur.lastrowid
        purchase = await checkout(42, account, Decimal('18.99'))
        order_id = purchase['id']
        order = await db.get_purchase_for_user(order_id, 42)
        assert order['referral_bonus'] == Decimal('0.9495') and order['referrer_id'] == 43
        await tickets.create_ticket(42, order_id, 'Fixture issue')
        async with connection.cursor() as cur:
            await cur.execute('UPDATE users SET balance=0 WHERE id=43')
        results = await asyncio.gather(refunds.refund_order(7, order_id, 'Fixture refund'),
                                       refunds.refund_order(8, order_id, 'Concurrent retry'))
        assert sum(result is not None for result in results) == 1
        assert (await db.get_user(42))['balance'] == 1000
        assert (await db.get_user(43))['balance'] == Decimal('-0.9495')
        async with connection.cursor() as cur:
            await cur.execute('SELECT COUNT(*) FROM order_refunds WHERE purchase_id=%s', (order_id,))
            assert (await cur.fetchone())[0] == 1
        report('concurrent refund credits once and reverses the recorded referral commission')
        order = await db.get_purchase_for_user(order_id, 42)
        assert order['status'] == 'refunded' and order['data'] == '' and order['password'] is None
        assert order['ticket_status'] == 'closed'
        await db.complete_user_purchase(account)
        assert (await db.get_purchase_for_user(order_id, 42))['status'] == 'refunded'
        report('refunded stock is retired, credentials removed, ticket closed and status remains final')
        async with connection.cursor() as cur:
            await cur.execute("INSERT INTO accounts (country,number,password,price,data) VALUES ('us','fixture-two','fixture-password',20,'PRIVATE_SESSION_FIXTURE')")
            second_account = cur.lastrowid
        second_order = await db.buy_account(44, second_account, 20, 'fixture', currency='RUB')
        assert second_order
        async with connection.cursor() as cur:
            await cur.execute(f"""CREATE TRIGGER fixture_refund_failure BEFORE INSERT ON admin_audit_log
                FOR EACH ROW BEGIN IF NEW.action='order_refund' AND NEW.target_id='{second_order}' THEN
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Fixture rollback'; END IF; END""")
        try:
            await refunds.refund_order(7, second_order, 'Rollback fixture')
        except aiomysql.OperationalError:
            pass
        else:
            raise AssertionError('Expected audit failure')
        assert (await db.get_user(44))['balance'] == 80
        assert (await db.get_purchase_for_user(second_order, 44))['status'] == 'issued'
        async with connection.cursor() as cur:
            await cur.execute('DROP TRIGGER fixture_refund_failure')
        report('failed audit rolls back balance, refund record and inventory changes')
        async with connection.cursor() as cur:
            await cur.execute('UPDATE purchases SET paid_amount=NULL WHERE id=%s', (second_order,))
        try:
            await refunds.refund_order(7, second_order, 'Unknown amount')
        except ValueError:
            pass
        else:
            raise AssertionError('Legacy amount was guessed')
        async with connection.cursor() as cur:
            await cur.execute('UPDATE purchases SET paid_amount=20 WHERE id=%s', (second_order,))
        report('legacy orders with unknown paid amounts cannot receive fabricated refunds')
        password = secrets.token_hex(32)
        async with connection.cursor() as cur:
            for host in ('localhost', '127.0.0.1'):
                await cur.execute(f"CREATE USER 'backup_fixture'@'{host}' IDENTIFIED BY '{password}'")
                await cur.execute(f"GRANT ALL PRIVILEGES ON `{name}`.* TO 'backup_fixture'@'{host}'")
        values = dict(DB_HOST='127.0.0.1', DB_PORT='3306', DB_SOCKET='/run/mysqld/mysqld.sock', DB_USER='backup_fixture', DB_PASSWORD=password, DB_NAME=name)
        with tempfile.TemporaryDirectory(prefix='finance-backup-fixture-') as directory:
            root = Path(directory)
            key = root / 'key'; key.write_text(secrets.token_urlsafe(48)); key.chmod(0o600)
            env = dict(os.environ, RESTIC_REPOSITORY=str(root / 'repository'), RESTIC_PASSWORD_FILE=str(key))
            backup_db.initialize(env)
            with tempfile.TemporaryDirectory(dir=root) as run_directory:
                backup_db.backup(values, env, run_directory)
            for file in (root / 'repository').rglob('*'):
                if file.is_file():
                    assert b'PRIVATE_SESSION_FIXTURE' not in file.read_bytes()
                    assert password.encode() not in file.read_bytes()
            report('limited application account produces an encrypted restic backup with no plaintext SQL files')
            with tempfile.TemporaryDirectory(dir=root) as verify_directory:
                restored = backup_db.verify(values, env, verify_directory)
                assert restored['rows']['users'] == 3 and restored['rows']['purchases'] == 2
                assert restored['rows']['order_refunds'] == 1 and restored['rows']['support_tickets'] == 1
            assert (await db.get_user(42))['balance'] == 1000
            async with connection.cursor() as cur:
                await cur.execute("SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME LIKE 'session_restore_check_%'")
                assert (await cur.fetchone())[0] == 0
            report('real restore into a restricted temporary database succeeds and leaves production fixture unchanged')
            before = json.loads(backup_db.restic(env, 'snapshots', '--json'))
            try:
                with tempfile.TemporaryDirectory(dir=root) as run_directory:
                    backup_db.backup(values | {'DB_NAME': 'missing_fixture_database'}, env, run_directory)
            except ValueError:
                pass
            else:
                raise AssertionError('Failed dump was accepted')
            after = json.loads(backup_db.restic(env, 'snapshots', '--json'))
            assert {r['id'] for r in before} == {r['id'] for r in after}
            report('failed SQL dump is rejected and its partial snapshot is removed')
            old_config = (root / 'repository/config').read_bytes()
            wrong_key = root / 'wrong-key'; wrong_key.write_text('fixture-wrong-key'); wrong_key.chmod(0o600)
            try:
                backup_db.initialize(env | {'RESTIC_PASSWORD_FILE': str(wrong_key)})
            except ValueError:
                pass
            else:
                raise AssertionError('Wrong key was accepted')
            assert (root / 'repository/config').read_bytes() == old_config
            backup_db.restic(env, 'cat', 'config')
            report('wrong encryption key cannot reinitialize or overwrite an existing backup repository')
        print(f'All {len(checks)} finance and backup integration scenarios passed.', flush=True)
    finally:
        if db.pool:
            db.pool.close(); await db.pool.wait_closed(); db.pool = None
        async with connection.cursor() as cur:
            await cur.execute(f'DROP DATABASE IF EXISTS `{name}`')
            for host in ('localhost', '127.0.0.1'):
                await cur.execute(f"DROP USER IF EXISTS 'backup_fixture'@'{host}'")
        connection.close()


if __name__ == '__main__':
    asyncio.run(main())
