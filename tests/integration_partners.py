"""Synthetic multi-bot ledger + HTTP ACL against disposable localhost MariaDB only."""
import asyncio
from decimal import Decimal as D
from pathlib import Path
import sys
from uuid import uuid4
from unittest.mock import patch,AsyncMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_payments import db,config
from test_miniapp import TEST_TOKEN,signed_data
from inventory_fixture import confirm_fixture_account
from database import partners,refunds,referrals,commerce
from database.admin_tools import _transaction
from miniapp import server,storage,wallet
from services.partner_runtime import claim
from utils.partner_context import CURRENT
from aiohttp.test_utils import TestClient,TestServer
import aiomysql


async def main():
    name='partner_fixture_'+uuid4().hex
    db.DB_CONFIG=dict(host='127.0.0.1',port=13309,user='root',password='',db=name,autocommit=True)
    config.ADMIN_IDS=[99]
    conn=await aiomysql.connect(host='127.0.0.1',port=13309,user='root',password='',autocommit=True)
    async def sql(query,args=()):
        async with conn.cursor() as cur:await cur.execute(query,args);return await cur.fetchall()
    async def denied(action,error=PermissionError):
        try:await action()
        except error:return
        raise AssertionError('Forbidden action succeeded')
    async def enter(identity):return CURRENT.set(await partners.get(identity))
    async def account(n):
        result=await db.add_account('auto','+1','+15550000'+str(n),'fixture-password',100,'SYNTHETIC_SESSION_'+str(n),90000+n)
        await confirm_fixture_account(result,'permanent');return result
    try:
        await db.init_db();await sql(f'USE `{name}`')
        for u in (99,42,43,44,45):await db.create_user(u,'fixture_'+str(u))
        await sql('UPDATE users SET balance=1000 WHERE id IN (42,43,44)')
        for identity,user in ((777001,43),(777002,44)):
            await partners.submit(user,identity,'fixture_'+str(identity),b'ENCRYPTED_FIXTURE')
            assert (await partners.get(identity))['status']=='pending'
            await denied(lambda:partners.enable(user,identity,True))
            await partners.enable(99,identity,True)
        assert 'token_cipher' not in partners.public(await partners.get(777001))
        # Lease exclusion, renewal, expiry takeover and approval-owned switch.
        assert await claim(777001,'lease-a')
        assert not await claim(777001,'lease-b')
        assert await claim(777001,'lease-a')
        await sql('UPDATE partner_bots SET lease_until=DATE_SUB(UTC_TIMESTAMP(),INTERVAL 1 SECOND) WHERE bot_id=777001')
        assert await claim(777001,'lease-b')
        q,_=await partners.quote_transfer(42,777001,'300')
        await asyncio.gather(partners.transfer(42,q),partners.transfer(42,q))
        assert (await sql('SELECT balance FROM users WHERE id=42'))[0][0]==700
        assert (await partners.balances(42,777001))['cash']==300
        async with _transaction() as cur:await partners.bonus_credit(cur,42,D(50),777001)
        a=await account(111);b=await account(112)
        ctx=await enter(777001)
        try:
            assert D(str((await db.get_user(42))['balance']))==350
            order=await storage.checkout(42,a,D(100))
            assert (await partners.balances(42))=={'cash':D(250),'bonus':D(0)}
            assert (await wallet.summary(42))['deposited']=='300.00000000'
            assert len((await partners.wallet_history(42))['items'])==2
            await denied(lambda:partners.close(99,777001))
            await denied(lambda:partners.set_content(43,777002,'welcome','Wrong shop'))
            await partners.set_content(43,777001,'welcome','Привет, {name}!')
            await partners.set_content(43,777001,'btn_buy','Мой каталог')
            await denied(lambda:partners.set_content(43,777001,'photo','../../.env'),ValueError)
            await partners.ban(43,777001,45,'fixture ban')
            await denied(lambda:partners.ban(43,777001,99,'owner'),ValueError)
        finally:CURRENT.reset(ctx)
        assert (await sql('SELECT cash,bonus FROM order_wallet_funding WHERE purchase_id=%s',(order['id'],)))[0]==(D(50),D(50))
        assert await partners.banned(45)
        assert not (await partners.content(777002))
        assert not (await partners.content(0))
        main_order=await storage.checkout(42,b,D(100))
        ctx=await enter(777002)
        try:
            assert not (await db.get_purchase_for_user(order['id'],42))
            assert not (await db.get_purchase_for_user(main_order['id'],42))
        finally:CURRENT.reset(ctx)
        # A paused shop cannot spend/accept transfers, but refunds preserve its buckets.
        await partners.enable(99,777001,False)
        await denied(lambda:partners.quote_transfer(42,777001,'10'),ValueError)
        await refunds.refund_order(99,order['id'],'Fixture refund')
        assert (await partners.balances(42,777001))=={'cash':D(300),'bonus':D(50)}
        assert await refunds.refund_order(99,order['id'],'Duplicate refund') is None
        await partners.enable(99,777001,True)
        c=await account(113)
        ctx=await enter(777001)
        try:late=await storage.checkout(42,c,D(100))
        finally:CURRENT.reset(ctx)
        before=(await sql('SELECT balance FROM users WHERE id=42'))[0][0]
        await asyncio.gather(partners.close(99,777001),partners.close(99,777001))
        assert (await sql('SELECT balance FROM users WHERE id=42'))[0][0]==before+250
        assert (await partners.balances(42,777001))=={'cash':D(0),'bonus':D(0)}
        assert (await sql('SELECT COUNT(*) FROM partner_settlements WHERE bot_id=777001'))[0][0]==1
        await denied(lambda:partners.enable(99,777001,True),ValueError)
        await refunds.refund_order(99,late['id'],'Late fixture refund')
        assert (await sql('SELECT balance FROM users WHERE id=42'))[0][0]==before+300
        assert (await partners.balances(42,0))['bonus']==50
        # Negative main bonus debt must not be exported as spendable partner cash.
        await sql('INSERT INTO scoped_wallets(bot_id,user_id,bonus) VALUES(0,44,-950)')
        q,_=await partners.quote_transfer(44,777002,'100')
        await denied(lambda:partners.transfer(44,q),ValueError)
        # Deposit bonus is separate, idempotent, and never eligible for cash transfers.
        assert await db.credit_paid_deposit(45,'100','crypto','fixture-deposit')==(110,10)
        assert await db.credit_paid_deposit(45,'100','crypto','fixture-deposit') is None
        assert (await sql('SELECT balance FROM users WHERE id=45'))[0][0]==100
        assert (await partners.balances(45,0))['bonus']==10
        await db.create_user(48,'compat_deposit_fixture')
        assert await db.add_deposit_with_first_bonus(48,20)==(22,2)
        assert await db.add_deposit_with_first_bonus(48,20)==(20,0)
        assert (await sql('SELECT balance FROM users WHERE id=48'))[0][0]==40
        assert (await partners.balances(48,0))['bonus']==2
        main_bonus_account=await account(117)
        await sql('UPDATE accounts SET price=25 WHERE id=%s',(main_bonus_account,))
        paid_with_bonus=await storage.checkout(48,main_bonus_account,D(25))
        assert (await sql('SELECT balance FROM users WHERE id=48'))[0][0]==17
        assert (await partners.balances(48,0))['bonus']==0
        await refunds.refund_order(99,paid_with_bonus['id'],'Main bonus refund')
        assert (await sql('SELECT balance FROM users WHERE id=48'))[0][0]==40
        assert (await partners.balances(48,0))['bonus']==2
        # Shared referral accrual is promotional money, never partner-refundable cash.
        await referrals.register_user(46,43,'referred_fixture',welcome_bonus=False)
        assert (await partners.balances(43,0))['bonus']==3
        await db.credit_paid_deposit(46,'100','crypto','referred-deposit')
        assert (await sql('SELECT balance FROM users WHERE id=43'))[0][0]==1000
        assert (await partners.balances(43,0))['bonus']==8
        async with _transaction() as cur:
            await referrals.lock_participants(cur,46,reverse_provider='crypto',reference='referred-deposit')
            assert await referrals.reverse_deposit(cur,46,'crypto','referred-deposit')==5
            assert await referrals.reverse_deposit(cur,46,'crypto','referred-deposit') is None
        assert (await partners.balances(43,0))['bonus']==3
        q,_=await partners.quote_transfer(46,777002,'100');await partners.transfer(46,q)
        d=await account(114);ctx=await enter(777002)
        try:referred=await storage.checkout(46,d,D(95))
        finally:CURRENT.reset(ctx)
        assert (await partners.balances(43,0))['bonus']==D('7.75')
        await refunds.refund_order(99,referred['id'],'Referral refund')
        assert (await partners.balances(43,0))['bonus']==3
        assert (await partners.balances(46,777002))['cash']==100
        # Bulk funding must be split across receipts without duplicating bonus money.
        await db.create_user(47,'bulk_fixture');await sql('UPDATE users SET balance=1000 WHERE id=47')
        q,_=await partners.quote_transfer(47,777002,'300');await partners.transfer(47,q)
        async with _transaction() as cur:await partners.bonus_credit(cur,47,D(150),777002)
        bulk_accounts=[await account(n) for n in (115,116)]
        ctx=await enter(777002)
        try:
            for identity in bulk_accounts:await commerce.add_to_cart(47,identity)
            bulk=await storage.checkout_cart(47,[{'account_id':identity,'price':'100'} for identity in bulk_accounts])
            assert (await partners.balances(47))=={'cash':D(250),'bonus':D(0)}
        finally:CURRENT.reset(ctx)
        portions=await sql('SELECT f.cash,f.bonus FROM order_wallet_funding f JOIN purchases p ON p.id=f.purchase_id WHERE p.user_id=47 ORDER BY p.id')
        assert portions==((D(0),D(100)),(D(50),D(50))),portions
        for identity in bulk['order_ids']:await refunds.refund_order(99,identity,'Bulk fixture refund')
        assert (await partners.balances(47,777002))=={'cash':D(300),'bonus':D(150)}
        # Close/transfer racing cannot lose money; an audit failure rolls closing back.
        await partners.submit(43,777003,'fixture_race',b'ENCRYPTED_FIXTURE');await partners.enable(99,777003,True)
        with patch.object(partners,'_record',AsyncMock(side_effect=OSError('fixture audit failure'))):
            await denied(lambda:partners.close(99,777003),OSError)
        assert (await partners.get(777003))['status']=='enabled'
        q,_=await partners.quote_transfer(42,777003,'20')
        before=(await sql('SELECT balance FROM users WHERE id=42'))[0][0]
        result=await asyncio.gather(partners.transfer(42,q),partners.close(99,777003),return_exceptions=True)
        assert all(not isinstance(r,BaseException) or isinstance(r,ValueError) for r in result),result
        assert (await sql('SELECT balance FROM users WHERE id=42'))[0][0]==before
        assert (await partners.balances(42,777003))['cash']==0
        print('PASS ledger: per-bot funds, bonus-first purchases, concurrent idempotent transfers/closing, scoped receipts, pause, bucket refunds, late refunds, debt, deposit bonus, leases',flush=True)
        await db.set_setting('miniapp_public_access','1')
        async with TestClient(TestServer(server.create_app(token=TEST_TOKEN,bot_username='fixture_main_bot'))) as client:
            def headers(user,identity=None):return {'Authorization':'tma '+signed_data(user),**({'X-Partner-ID':str(identity)} if identity else {})}
            owner=headers(44,777002);customer=headers(42,777002);root=headers(99)
            r=await client.get('/api/admin/identity',headers=owner);assert r.status==200,await r.text()
            assert (await r.json())['is_partner_owner']
            for path in ['/api/admin/users','/api/admin/partners','/api/admin/helpers','/api/admin/advertising','/api/admin/settings']:
                assert (await client.get(path,headers=owner)).status==403,path
            assert (await client.get('/api/admin/partner-content',headers=customer)).status==403
            r=await client.post('/api/admin/partner-content',headers=owner,json={'key':'btn_buy','value':'Витрина'});assert r.status==200,await r.text()
            assert (await partners.content(777002))['btn_buy']=='Витрина'
            assert (await client.get('/api/admin/partners',headers=root)).status==200
            assert (await client.post('/api/invoices',headers=customer,json={'amount':100})).status==409
            r=await client.post('/api/admin/partner-bans',headers=owner,json={'user_id':42,'reason':'HTTP fixture ban'});assert r.status==200,await r.text()
            assert (await client.get('/api/me',headers=headers(42))).status==403
            # Revoking this partner's ban cannot clear another partner's active ban.
            r=await client.post('/api/admin/partner-bans',headers=owner,json={'user_id':45,'reason':'own unban','enabled':False});assert r.status==200
            assert await partners.banned(45)
            await partners.ban(99,0,42,'root unban',False)
            assert not await partners.banned(42)
            # Holding the partner token must not allow forged main-store identities.
            with patch('test_miniapp.TEST_TOKEN','777002:partner-controlled-test-token'):
                forged={'Authorization':'tma '+signed_data(42),'X-Partner-ID':'777002'}
            assert (await client.get('/api/me',headers=forged)).status==401
            assert (await client.get('/api/me',headers=headers(42,777001))).status==403
            assert (await client.get('/api/me',headers=headers(42,'../../'))).status==400
            await db.set_setting('maintenance_mode','1')
            for h in [headers(42),customer]:
                r=await client.get('/api/me',headers=h);assert r.status==503,await r.text()
            await db.set_setting('maintenance_mode','0')
            r=await client.get('/api/me',headers=customer);assert r.status==200,await r.text()
            assert (await r.json())['partner_id']==777002
            assert CURRENT.get() is None
        print('PASS HTTP: main-token-only signatures, strict partner ACL, branding isolation, global bans/revocation, main-only invoices, disabled shops, shared maintenance, context cleanup',flush=True)
    finally:
        if db.pool:db.pool.close();await db.pool.wait_closed();db.pool=None
        try:await sql(f'DROP DATABASE IF EXISTS `{name}`')
        finally:conn.close()


if __name__=='__main__':asyncio.run(main())
