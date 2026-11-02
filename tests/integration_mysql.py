"""Integration checks against a disposable, local MySQL (never application config).

Run with: python tests/integration_mysql.py
Uses localhost:13307 root with an empty password; creates and removes a new,
random database. The repository .env is never loaded by this script.
"""
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_payments import db
import aiomysql
from database import admin_tools, tickets
from utils.order_status import order_status


async def main():
    connection = await aiomysql.connect(host='127.0.0.1', port=13307, user='root', password='', autocommit=True)
    name = 'ticket_integration_' + uuid4().hex
    try:
        async with connection.cursor() as cur:
            await cur.execute(f'CREATE DATABASE `{name}` COLLATE utf8mb4_unicode_ci')
            await cur.execute(f'USE `{name}`')
            # Legacy schema and a completed order, before the 2.0 migration.
            await cur.execute('CREATE TABLE users (id BIGINT PRIMARY KEY, balance DECIMAL(18,8) DEFAULT 0) ENGINE=InnoDB')
            await cur.execute('''CREATE TABLE accounts (
                id INT AUTO_INCREMENT PRIMARY KEY, country VARCHAR(255), code VARCHAR(50),
                number VARCHAR(255), password VARCHAR(255), price DECIMAL(10,2),
                data TEXT, status VARCHAR(50) DEFAULT 'available') ENGINE=InnoDB''')
            await cur.execute('''CREATE TABLE purchases (
                id INT AUTO_INCREMENT PRIMARY KEY, user_id BIGINT, account_id INT,
                date VARCHAR(255), FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE) ENGINE=InnoDB''')
            await cur.execute('INSERT INTO users (id, balance) VALUES (42, 100), (43, 0)')
            await cur.execute("INSERT INTO accounts (country, number, price, data, status) VALUES ('us', 'test', 999, %s, 'sold')",
                              ('✅ Сессия удалена (Покупка завершена)',))
            await cur.execute("INSERT INTO purchases (user_id, account_id, date) VALUES (42, 1, 'legacy')")
        db.DB_CONFIG = dict(host='127.0.0.1', port=13307, user='root', password='', db=name, autocommit=True)
        for _ in range(2):
            await db.init_db()
            db.pool.close()
            await db.pool.wait_closed()
            db.pool = None
        await db.init_db()
        legacy = await db.get_purchase_for_user(1, 42)
        assert legacy['status'] == 'completed' and legacy['paid_amount'] is None
        print('PASS: legacy order migration and repeated startup')
        async with connection.cursor() as cur:
            await cur.execute("INSERT INTO accounts (country, number, price, data) VALUES ('us', 'fixture2', 25, 'test-session')")
            account_id = cur.lastrowid
        order_id = await db.buy_account(42, account_id, 25, 'test date', currency='RUB')
        assert order_id
        order = await db.get_purchase_for_user(order_id, 42)
        assert order['status'] == 'issued' and order['paid_amount'] == 25
        print('PASS: purchase amount and issued state saved atomically')
        first, second = await asyncio.gather(
            tickets.create_ticket(42, order_id, 'First question'),
            tickets.create_ticket(42, order_id, 'Second question'),
        )
        assert first == second
        async with connection.cursor() as cur:
            await cur.execute('SELECT COUNT(*) FROM support_messages WHERE ticket_id = %s', (first,))
            assert (await cur.fetchone())[0] == 2
        assert 'Проблема' in order_status(await db.get_purchase_for_user(order_id, 42))
        print('PASS: concurrent submissions share one ticket and retain both messages')
        assert await tickets.get_ticket(first, 43) is None
        assert not await tickets.history(first, 43)
        for operation in (tickets.create_ticket(43, order_id, 'Unauthorized'), tickets.reply(first, 43, 'Unauthorized')):
            try:
                await operation
            except ValueError:
                pass
            else:
                raise AssertionError('Ownership check failed')
        print('PASS: unauthorized ticket reads, creation and replies denied')
        await tickets.reply(first, 7, 'Support reply', admin=True)
        assert (await tickets.get_ticket(first))['status'] == 'waiting_user'
        assert await tickets.close_ticket(first, 7) == 42
        assert await tickets.close_ticket(first, 7) is None
        await tickets.reply(first, 42, 'Reopen')
        assert (await tickets.get_ticket(first))['status'] == 'open'
        await db.complete_user_purchase(account_id)
        assert 'Проблема' in order_status(await db.get_purchase_for_user(order_id, 42))
        await tickets.close_ticket(first, 7)
        assert order_status(await db.get_purchase_for_user(order_id, 42)) == 'Завершён'
        print('PASS: admin reply, close, idempotent close, user reopen and order completion')
        try:
            await admin_tools.remove_account(7, account_id)
        except ValueError:
            pass
        else:
            raise AssertionError('Support history was not protected')
        assert await db.get_purchase_for_user(order_id, 42)
        assert await tickets.get_ticket(first, 42)
        print('PASS: deleting an account cannot erase a support conversation')
        async with connection.cursor() as cur:
            await cur.execute("INSERT INTO accounts (country, number, price, data) VALUES ('us', 'fixture3', 25, 'test-session')")
            next_account = cur.lastrowid
            await cur.execute("""CREATE TRIGGER support_test_failure BEFORE INSERT ON support_messages
                FOR EACH ROW BEGIN IF NEW.body = '__ROLLBACK__' THEN
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Intentional test failure'; END IF; END""")
        next_order = await db.buy_account(42, next_account, 25, 'test date', currency='RUB')
        try:
            await tickets.create_ticket(42, next_order, '__ROLLBACK__')
        except aiomysql.OperationalError:
            pass
        else:
            raise AssertionError('Expected a forced database error')
        assert await tickets.ticket_for_order(next_order, 42) is None
        assert await tickets.create_ticket(42, next_order, 'Successful retry')
        print('PASS: failed message rolls back ticket creation; retry succeeds')
        async with connection.cursor() as cur:
            await cur.execute('SELECT action, details FROM admin_audit_log WHERE target_type = %s AND target_id = %s ORDER BY id',
                              ('ticket', str(first)))
            events = await cur.fetchall()
            assert [event[0] for event in events] == ['ticket_reply', 'ticket_close', 'ticket_close']
            assert all('Support reply' not in event[1] for event in events)
        print('PASS: admin replies and closures are audited without copying message bodies')
        async with connection.cursor() as cur:
            await cur.execute("INSERT INTO accounts (country, number, price, data) VALUES ('us', 'fixture4', 19.99, 'test-session')")
            referral_account = cur.lastrowid
        referral_order = await db.buy_account_with_referral(
            42, referral_account, 19.99, 'test date', 5, 5, referrer_id=43, currency='RUB')
        assert referral_order
        assert (await db.get_purchase_for_user(referral_order, 42))['paid_amount'] == admin_tools.Decimal('18.99')
        print('PASS: referral purchase records the discounted ruble amount')
        print('All 9 MySQL integration scenarios passed.')
    finally:
        if db.pool is not None:
            db.pool.close()
            await db.pool.wait_closed()
            db.pool = None
        async with connection.cursor() as cur:
            await cur.execute(f'DROP DATABASE IF EXISTS `{name}`')
        connection.close()


if __name__ == '__main__':
    asyncio.run(main())
