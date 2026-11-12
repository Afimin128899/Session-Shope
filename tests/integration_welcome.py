"""Disposable MariaDB :13307 and localhost :8092. No project .env, Telegram or payments."""
import asyncio
from decimal import Decimal as D
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch
from uuid import uuid4

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from test_payments import db,config
from test_miniapp import TEST_TOKEN,signed_data
from database import welcome,rewards,referrals
from handlers.user import start
from miniapp.server import create_app
from aiohttp import web,ClientSession
import aiomysql


async def main():
    name='welcome_'+uuid4().hex
    config.ADMIN_IDS=[42];config.BOT_TOKEN=TEST_TOKEN
    db.DB_CONFIG=dict(host='127.0.0.1',port=13307,user='root',password='',db=name,autocommit=True)
    conn=await aiomysql.connect(host='127.0.0.1',port=13307,user='root',password='',autocommit=True)
    runner=None
    async def sql(query,args=()):
        async with conn.cursor() as cur:
            await cur.execute(query,args);return await cur.fetchall()
    async def balance(user):return D(str((await db.get_user(user))['balance']))
    async def count(table,user,column='user_id'):
        return (await sql(f'SELECT COUNT(*) FROM {table} WHERE {column}=%s',(user,)))[0][0]
    def report(message):print('PASS: '+message,flush=True)
    try:
        await db.init_db();await sql(f'USE `{name}`')
        await sql('INSERT INTO users(id,balance) VALUES(42,0),(43,17.50),(44,0)')
        async with conn.cursor() as cur:await welcome.init_schema(cur);await welcome.init_schema(cur)
        await db.create_user(43,'existing',welcome_bonus=True)
        await db.create_user_with_referrer(43,44,'existing-renamed')
        assert await balance(43)==D('17.50') and await welcome.received(43)==0
        assert await db.get_referrer(43) is None and await balance(44)==0
        await db.create_user(45,'administrative')
        assert await balance(45)==0 and await welcome.received(45)==0
        report('Migration and existing logins do not grant money retroactively; administrative creation is not a login')

        message=NS(from_user=NS(id=200,username='first_bot',first_name='Fixture'),answer=AsyncMock())
        with patch.object(start,'main_menu',AsyncMock(return_value=None)),patch.object(start,'answer_screen',AsyncMock()):
            await asyncio.gather(*(start.cmd_start(message,NS(args='ref_44')) for _ in range(10)))
        assert await balance(200)==4 and await welcome.received(200)==4
        assert message.answer.await_count==1 and await count('welcome_bonuses',200)==1
        assert await balance(44)==3 and (await referrals.summary(44))['daily']['issued']=='3.00000000'
        assert await count('referral_rewards',200)==1
        assert (await db.get_user(200))['first_deposit_bonus_used']==0
        assert D((await rewards.status(200))['paid'])==0
        assert not (await rewards.status(200))['eligible']
        assert await count('payment_logs',200)==0
        report('Ten concurrent first starts grant RUB 4 once and announce it once; inviter gets only RUB 3, while wheel and first-deposit bonus remain untouched')

        runner=web.AppRunner(create_app(enable_cart=True,customer_enabled=True,admin_enabled=True,token=TEST_TOKEN,bot=NS(),bot_username='welcome_fixture_bot'),access_log=None)
        await runner.setup();await web.TCPSite(runner,'127.0.0.1',8092).start()
        async with ClientSession() as client:
            async def me(user,raw=None):
                headers={'Authorization':'tma '+(signed_data(user) if raw is None else raw)}
                response=await client.get('http://127.0.0.1:8092/api/me?user_id=999&welcome_bonus=100',headers=headers)
                result=await response.json();assert response.status==200,(response.status,result)
                return result
            results=await asyncio.gather(*(me(201) for _ in range(16)))
            assert all(D(row['balance'])==4 and D(row['welcome_bonus'])==4 for row in results)
            assert not await db.get_user(999) and await count('welcome_bonuses',201)==1
            with patch.object(start,'main_menu',AsyncMock(return_value=None)),patch.object(start,'answer_screen',AsyncMock()):
                second=NS(from_user=NS(id=201,username='then_bot',first_name='Fixture'),answer=AsyncMock())
                await start.cmd_start(second,NS(args='ref_44'))
            assert second.answer.await_count==0 and await balance(201)==4 and await db.get_referrer(201) is None
            before=await balance(200);assert D((await me(200))['welcome_bonus'])==4 and await balance(200)==before
            result=await client.get('http://127.0.0.1:8092/api/me',headers={'Authorization':'tma '+signed_data(203)+'tampered'})
            assert result.status==401 and not await db.get_user(203)
            report('Sixteen simultaneous Mini App requests credit only the signed user; switching between Mini App and bot or spoofing JSON/query/auth cannot yield a second credit')

            with patch.object(welcome,'_record',AsyncMock(side_effect=OSError('Injected audit failure'))):
                try:await db.create_user_with_referrer(202,44,'rollback_fixture')
                except OSError:pass
                else:raise AssertionError('Injected failure was swallowed')
            assert not await db.get_user(202) and await count('welcome_bonuses',202)==0 and await count('referrals',202,'referral_id')==0
            assert await balance(44)==3
            assert await db.create_user_with_referrer(202,44,'retry')==4
            assert await balance(202)==4 and await balance(44)==6
            assert await count('welcome_bonuses',202)==1
            report('A failed receipt/audit rolls back registration and both bonuses; retry grants each exactly once')

            first=await db.credit_paid_deposit(200,100,'crypto','welcome-followed-by-real-deposit')
            assert first==(110.0,10.0) and await balance(200)==114 and await balance(44)==11
            assert (await rewards.status(200))['eligible']
            async with conn.cursor() as cur:await welcome.init_schema(cur)
            assert await db.create_user_with_referrer(200,None,'changed_name')==0
            assert await balance(200)==114 and await count('welcome_bonuses',200)==1
            report('A later real RUB 100 top-up still gives the first 10% bonus and exactly 5% referral reward; restart migration cannot restore the welcome credit')
            if '--serve' in sys.argv:
                print('BROWSER FIXTURE: http://127.0.0.1:8092 customer=201 old=43',flush=True)
                await asyncio.Event().wait()
    finally:
        if runner:await runner.cleanup()
        if db.pool:db.pool.close();await db.pool.wait_closed();db.pool=None
        try:await sql(f'DROP DATABASE IF EXISTS `{name}`')
        finally:conn.close()


if __name__=='__main__':asyncio.run(main())
