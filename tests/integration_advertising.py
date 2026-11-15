"""Disposable localhost MariaDB only; never reads production DB credentials."""
import asyncio
from pathlib import Path
import sys
from uuid import uuid4
from unittest.mock import AsyncMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_payments import db,config
from database import advertising as ads,referrals,welcome
from miniapp import server
from test_miniapp import TEST_TOKEN,signed_data
from aiohttp.test_utils import TestClient,TestServer
import aiomysql


async def main():
    name='advertising_fixture_'+uuid4().hex
    db.DB_CONFIG=dict(host='127.0.0.1',port=13308,user='root',password='',db=name,autocommit=True)
    config.ADMIN_IDS=[99]
    conn=await aiomysql.connect(host='127.0.0.1',port=13308,user='root',password='',autocommit=True)
    async def sql(query,args=()):
        async with conn.cursor() as cur:
            await cur.execute(query,args);return await cur.fetchall()
    try:
        await db.init_db();await sql(f'USE `{name}`')
        for user in [99,42,43,102]:await db.create_user(user,'fixture_'+str(user))
        await ads.set_helper(99,42,True);await ads.set_helper(99,43,True)
        a=await ads.create_campaign(42,'Канал A <test>');b=await ads.create_campaign(43,'Канал B')
        await referrals.register_user(101,43,'customer',welcome_bonus=False,ad_token=a['token'])
        await referrals.register_user(101,43,'customer',welcome_bonus=False,ad_token=b['token'])
        await referrals.register_user(102,None,welcome_bonus=False,ad_token=a['token'])
        assert (await sql('SELECT COUNT(*) FROM advertising_users'))[0][0]==1
        assert (await sql('SELECT COUNT(*) FROM referrals'))[0][0]==0
        assert (await sql('SELECT COUNT(*) FROM referral_rewards'))[0][0]==0
        assert (await ads.campaigns(42))[0]['users_count']==1
        assert (await ads.campaigns(43))[0]['users_count']==0
        assert await ads.campaign_users(43,a['id']) is None
        # Same signup races across two sources: one registration and one source win.
        await asyncio.gather(*(referrals.register_user(140,None,'race',welcome_bonus=False,ad_token=c['token']) for c in [a,b]))
        assert (await sql('SELECT COUNT(*) FROM advertising_users WHERE user_id=140'))[0][0]==1
        with patch.object(welcome,'credit_new_user',AsyncMock(side_effect=OSError('fixture rollback'))):
            try:await referrals.register_user(150,None,ad_token=a['token'])
            except OSError:pass
            else:raise AssertionError('Expected registration failure')
        assert not await db.get_user(150)
        assert (await sql('SELECT COUNT(*) FROM advertising_users WHERE user_id=150'))[0][0]==0
        # A revoked helper cannot read/create, and old links stop acquiring users.
        await ads.set_helper(99,42,False)
        for action in [lambda:ads.campaigns(42),lambda:ads.create_campaign(42,'closed')]:
            try:await action()
            except PermissionError:pass
            else:raise AssertionError('Revoked helper retained access')
        await referrals.register_user(151,None,welcome_bonus=False,ad_token=a['token'])
        assert (await sql('SELECT COUNT(*) FROM advertising_users WHERE user_id=151'))[0][0]==0
        await ads.set_helper(99,42,True)
        for user in range(200,226):await referrals.register_user(user,None,welcome_bonus=False,ad_token=a['token'])
        first=await ads.campaign_users(42,a['id']);second=await ads.campaign_users(42,a['id'],1)
        assert len(first['items'])==15 and first['has_more'] and not second['has_more']
        assert not {r['user_id'] for r in first['items']}&{r['user_id'] for r in second['items']}
        async with db._get_pool().acquire() as connection:
            async with connection.cursor() as cur:await ads.init_schema(cur,name)
        async with TestClient(TestServer(server.create_app(token=TEST_TOKEN,bot_username='fixture_bot'))) as client:
            helper={'Authorization':'tma '+signed_data(42)}
            owner={'Authorization':'tma '+signed_data(99)}
            r=await client.get('/api/admin/advertising',headers=helper);assert r.status==200,await r.text()
            assert (await r.json())['items'][0]['name']=='Канал A <test>'
            assert (await client.get('/api/admin/advertising/'+str(b['id'])+'/users',headers=helper)).status==404
            assert (await client.get('/api/admin/users',headers=helper)).status==403
            assert (await client.get('/api/admin/helpers',headers=helper)).status==403
            assert (await client.get('/api/admin/advertising',headers=owner)).status==403
            assert (await client.post('/api/admin/helpers',headers=owner,json={'user_id':42,'enabled':False})).status==200
            assert (await client.get('/api/admin/advertising',headers=helper)).status==403
        assert (await sql("SELECT COUNT(*) FROM admin_audit_log WHERE action='helper_role'"))[0][0]>=4
        assert (await sql('SELECT COUNT(*) FROM referrals'))[0][0]==0
        assert (await sql('SELECT COUNT(*) FROM referral_rewards'))[0][0]==0
        print('PASS: MariaDB schema/repeat migration, one helper role, audited assignment/revocation, owner isolation, concurrent deduplication, registration rollback, pagination and zero referral payouts')
    finally:
        if db.pool:db.pool.close();await db.pool.wait_closed();db.pool=None
        try:await sql(f'DROP DATABASE IF EXISTS `{name}`')
        finally:conn.close()


if __name__=='__main__':asyncio.run(main())
