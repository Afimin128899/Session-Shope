"""Real shared-DB Mini App tests. Uses only disposable localhost:13307 MySQL.

--serve keeps the isolated fixture at localhost:8085 for browser checks.
Never imports the repository .env or connects to production services.
"""
import asyncio
from decimal import Decimal
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import aiomysql
from aiohttp import ClientSession, web
from test_payments import db
from test_miniapp import TEST_TOKEN, signed_data
from miniapp.server import create_app
from database import commerce
from services import payments, market_notifications
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta


async def main():
    name = 'miniapp_integration_' + uuid4().hex
    connection = await aiomysql.connect(host='127.0.0.1', port=13307, user='root', password='', autocommit=True)
    runner = None
    try:
        db.DB_CONFIG = dict(host='127.0.0.1', port=13307, user='root', password='', db=name, autocommit=True)
        await db.init_db()
        async with connection.cursor() as cur:
            await cur.execute(f'USE `{name}`')
            await cur.execute("INSERT INTO users (id, balance, balance_usdt) VALUES (42, 1000, 12.5), (43, 0, 0)")
            await cur.execute("INSERT INTO referrals (referral_id, referrer_id) VALUES (42, 43)")
            await cur.execute('UPDATE referral_settings SET discount_pct = 5, bonus_pct = 5 WHERE id = 1')
            await cur.execute('DELETE FROM categories')
            categories = [('us', 'США', '🇺🇸'), ('ru', 'Россия', '🇷🇺'), ('kz', 'Казахстан', '🇰🇿'), ('gb', 'Великобритания', '🇬🇧'), ('de', 'Германия', '🇩🇪'), ('nl', 'Нидерланды', '🇳🇱')]
            for slug, label, emoji in categories:
                await cur.execute('INSERT INTO categories (slug, name, emoji, is_active) VALUES (%s, %s, %s, 1)', (slug, label, emoji))
            for index in range(12):
                await cur.execute('INSERT INTO accounts (country, number, password, price, data, telegram_user_id) VALUES (%s,%s,%s,%s,%s,%s)',
                                  (categories[index % 6][0], f'+15550000{index:03}', 'fixture-password', 200 + index * 25, 'NEVER_EXPOSE_SESSION', 9000000000 + index))
        bot = SimpleNamespace(get_chat_member=None)
        runner = web.AppRunner(create_app(token=TEST_TOKEN, bot=bot, bot_username='session_test_bot'), access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 8085)
        await site.start()
        headers = {'Authorization': 'tma ' + signed_data()}
        async with ClientSession() as session:
            assert (await session.get('http://127.0.0.1:8085/api/catalog')).status == 401
            res = await session.get('http://127.0.0.1:8085/api/catalog', headers=headers)
            assert res.status == 200
            data = await res.json()
            assert len(data['items']) == 12
            assert 'NEVER_EXPOSE_SESSION' not in str(data)
            assert 'fixture-password' not in str(data)
            assert all('•••' in i['phone'] for i in data['items'])
            print('PASS: authenticated catalog reads shared stock without exposing credentials')
            selected = data['items'][0]
            payload = {'account_id': selected['id'], 'price': selected['price']}
            async def buy():
                response = await session.post('http://127.0.0.1:8085/api/purchase', headers=headers, json=payload)
                return response.status, await response.json()
            results = await asyncio.gather(buy(), buy())
            assert sorted(r[0] for r in results) == [201, 409]
            purchase = next(r[1] for r in results if r[0] == 201)
            bot_order = await db.get_purchase_for_user(purchase['id'], 42)
            assert bot_order['paid_amount'] == Decimal(selected['price'])
            print('PASS: concurrent purchase only charges once; order appears in bot DB')
            res = await session.get('http://127.0.0.1:8085/api/me', headers=headers)
            me = await res.json()
            assert Decimal(me['balance']) == Decimal('1000') - Decimal(selected['price'])
            assert (await db.get_user(43))['balance'] > 0
            print('PASS: ruble balance and referral bonus synchronize with bot')
            orders = await (await session.get('http://127.0.0.1:8085/api/orders', headers=headers)).json()
            assert orders['items'][0]['id'] == purchase['id']
            assert (await session.get(f"http://127.0.0.1:8085/api/orders/{purchase['id']}",
                                      headers={'Authorization': 'tma ' + signed_data(43)})).status == 404
            print('PASS: orders visible to owner only')
            current = await (await session.get('http://127.0.0.1:8085/api/catalog', headers=headers)).json()
            assert selected['id'] not in {i['id'] for i in current['items']}
            another = current['items'][0]
            async with connection.cursor() as cur:
                await cur.execute('UPDATE accounts SET price = price + 100 WHERE id = %s', (another['id'],))
            response = await session.post('http://127.0.0.1:8085/api/purchase', headers=headers,
                                          json={'account_id': another['id'], 'price': another['price']})
            assert response.status == 409 and (await response.json())['code'] == 'price_changed'
            print('PASS: admin stock and price changes reflected; stale price cannot be charged')
            await db.complete_user_purchase(bot_order['account_id'])
            order = await (await session.get(f"http://127.0.0.1:8085/api/orders/{purchase['id']}", headers=headers)).json()
            assert order['status'] == 'completed' and 'data' not in order
            print('PASS: order completion from bot synchronizes to Mini App')
            async with connection.cursor() as cur:
                await cur.execute("INSERT INTO settings (`key`,`value`) VALUES ('maintenance_mode','1') ON DUPLICATE KEY UPDATE `value`='1'")
            assert (await session.get('http://127.0.0.1:8085/api/catalog', headers=headers)).status == 503
            async with connection.cursor() as cur:
                await cur.execute("UPDATE settings SET `value`='0' WHERE `key`='maintenance_mode'")
            print('PASS: bot maintenance mode enforced by Mini App')
            from integration_market import marketplace_scenarios
            await marketplace_scenarios(session, connection, headers)
            print('All Mini App and marketplace integration scenarios passed.', flush=True)
        if '--serve' in sys.argv:
            print('Isolated browser fixture listening on localhost:8085', flush=True)
            await asyncio.Event().wait()
    finally:
        if runner: await runner.cleanup()
        if db.pool:
            db.pool.close(); await db.pool.wait_closed(); db.pool = None
        async with connection.cursor() as cur:
            await cur.execute(f'DROP DATABASE IF EXISTS `{name}`')
        connection.close()


if __name__ == '__main__':
    asyncio.run(main())
