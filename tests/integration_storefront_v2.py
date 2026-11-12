"""Category checkout/chat/access against disposable localhost MariaDB only."""
import asyncio
from decimal import Decimal
from pathlib import Path
import sys
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_payments import db
from test_miniapp import TEST_TOKEN,signed_data
from inventory_fixture import confirm_fixture_account
from miniapp import server
from database import direct_chat
import aiomysql
from aiohttp.test_utils import TestClient,TestServer


async def main():
    name='storefront_v2_'+uuid4().hex
    db.DB_CONFIG=dict(host='127.0.0.1',port=13307,user='root',password='',db=name,autocommit=True)
    conn=await aiomysql.connect(host='127.0.0.1',port=13307,user='root',password='',autocommit=True)
    async def sql(query,args=()):
        async with conn.cursor() as cur:
            await cur.execute(query,args);return await cur.fetchall()
    server.config.ADMIN_IDS=[42]
    try:
        await db.init_db();await sql(f'USE `{name}`')
        await sql('INSERT INTO users(id,balance) VALUES(42,500),(43,1000),(44,1000)')
        account=await db.add_account('auto','+1','+15550000111','fixture-2fa',100,'SYNTHETIC_SESSION',90001)
        await confirm_fixture_account(account,'permanent')
        admin={'Authorization':'tma '+signed_data(42)}
        own={'Authorization':'tma '+signed_data(43)}
        other={'Authorization':'tma '+signed_data(44)}
        async with TestClient(TestServer(server.create_app(token=TEST_TOKEN,bot_username='fixture_bot'))) as c:
            assert (await c.get('/api/category-market',headers=own)).status==403
            r=await c.post('/api/admin/app-access',headers=admin,json={'enabled':True})
            assert r.status==200,await r.text()
            assert (await r.json())['enabled'] is True
            assert (await sql("SELECT COUNT(*) FROM admin_audit_log WHERE action='miniapp_public_access'"))[0][0]==1
            r=await c.get('/api/category-market',headers=own)
            assert r.status==200,await r.text()
            items=(await r.json())['items'];assert len(items)==1,items
            assert items[0]['name']=='США Вечный СБ' and items[0]['count']==1
            r=await c.post('/api/category-quote',headers=own,json={'mode':'auto','nation':items[0]['nation']})
            assert r.status==200,await r.text()
            quote=await r.json();assert Decimal(quote['price'])==100
            assert 'number' not in quote and 'account_id' not in quote
            assert (await c.post('/api/category-buy',headers=other,json={'token':quote['token']})).status==409
            r=await c.post('/api/category-buy',headers=own,json={'token':quote['token'],'price':'0','account_id':999})
            assert r.status==201,await r.text()
            order=await r.json()
            assert Decimal(str((await db.get_user(43))['balance']))==900
            assert (await c.post('/api/category-buy',headers=own,json={'token':quote['token']})).status==409
            assert Decimal(str((await db.get_user(43))['balance']))==900
            r=await c.get('/api/orders/'+str(order['id']),headers=own)
            assert r.status==200,await r.text()
            receipt=await r.json();assert receipt['number']=='+15550000111' and receipt['password']=='fixture-2fa'
            assert (await c.get('/api/orders/'+str(order['id']),headers=other)).status==404
            for method,path in [('GET','/api/cart'),('POST','/api/cart'),('POST','/api/cart/checkout')]:
                assert (await c.request(method,path,headers=own,json={'account_id':account})).status==404
            print('PASS: closed-by-default access, audited admin opening, category auto-selection, private receipt, single debit, no cart routes',flush=True)
            # Long Cyrillic text exercises the body limit and utf8mb4 storage.
            text='<script>Тест</script>\n'+'Я'*3900
            r=await c.post('/api/chat',headers=own,json={'body':text,'user_id':44})
            assert r.status==201,await r.text()
            history=await (await c.get('/api/chat?user_id=44',headers=own)).json()
            assert len(history['items'])==1 and history['items'][0]['body']==text
            assert not (await (await c.get('/api/chat',headers=other)).json())['items']
            assert (await c.get('/api/admin/conversations',headers=own)).status==403
            inbox=await (await c.get('/api/admin/conversations',headers=admin)).json()
            assert len(inbox['items'])==1 and inbox['items'][0]['user_id']==43
            r=await c.post('/api/admin/conversations/43',headers=admin,json={'body':'Ответ поддержки','user_id':44})
            assert r.status==201,await r.text()
            history=await (await c.get('/api/chat',headers=own)).json()
            assert [m['author_role'] for m in history['items']]==['user','admin']
            assert (await sql('SELECT COUNT(*) FROM support_tickets'))[0][0]==0
            for i in range(52):await direct_chat.append(43,'user','Page '+str(i))
            latest=await direct_chat.history(43);assert latest['has_more'] and len(latest['items'])==50
            older=await direct_chat.history(43,latest['items'][0]['id'])
            assert len(older['items'])==4 and not older['has_more']
            assert not set(m['id'] for m in latest['items'])&set(m['id'] for m in older['items'])
            r=await c.post('/api/admin/app-access',headers=admin,json={'enabled':False});assert r.status==200
            assert not (await r.json())['enabled']
            assert (await c.get('/api/category-market',headers=own)).status==403
            assert (await c.get('/api/category-market',headers=admin)).status==200
            assert Decimal(str((await db.get_user(43))['balance']))==900
            assert Decimal(str((await db.get_user(44))['balance']))==1000
            print('PASS: persistent Unicode chat, owner isolation, admin reply, cursor pagination, no tickets, public closing, balances preserved',flush=True)
    finally:
        if db.pool:db.pool.close();await db.pool.wait_closed();db.pool=None
        try:await sql(f'DROP DATABASE IF EXISTS `{name}`')
        finally:conn.close()


if __name__=='__main__':asyncio.run(main())
