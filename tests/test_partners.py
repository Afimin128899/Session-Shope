"""Offline multi-bot authorization, context lifetime and private-token storage."""
import os
import tempfile
from pathlib import Path
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase,TestCase
from unittest.mock import AsyncMock,patch
from cryptography.fernet import Fernet
from test_payments import config
from database import partners
from services import partner_tokens,partner_runtime as runtime
from utils.partner_context import CURRENT,CONTENT
from deploy.partner_key import ensure
from aiogram.types import Update


class TokenStorageTests(TestCase):
    def test_stable_private_key_and_encrypted_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'.env';path.write_text('FIXTURE=only\n')
            self.assertTrue(ensure(path));key=path.read_text().split('PARTNER_BOT_KEY=')[1].strip()
            saved=path.read_bytes();self.assertFalse(ensure(path));self.assertEqual(path.read_bytes(),saved)
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            with patch.dict(os.environ,{'PARTNER_BOT_KEY':key}):
                token='777001:synthetic-test-secret';encrypted=partner_tokens.encrypt(token)
                self.assertNotIn(token.encode(),encrypted)
                self.assertEqual(partner_tokens.decrypt(encrypted),token)
            with patch.dict(os.environ,{'PARTNER_BOT_KEY':Fernet.generate_key().decode()}):
                with self.assertRaisesRegex(ValueError,'ключ'):partner_tokens.decrypt(encrypted)

    def test_missing_key_disables_application(self):
        with patch.dict(os.environ,{'PARTNER_BOT_KEY':''}):
            with self.assertRaises(ValueError):partner_tokens.encrypt('fixture')


class PartnerPoliciesTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.p={'bot_id':777001,'owner_id':42,'status':'enabled','content_json':'{"welcome":"Fixture"}'}
        self.ctx=CURRENT.set(self.p);self.addCleanup(CURRENT.reset,self.ctx)

    async def test_owner_privileges_never_inherit_into_partner_bot(self):
        with patch.object(config,'ADMIN_IDS',[99]):
            for actor in (42,99):
                with self.assertRaises(PermissionError):partners.owner(actor)
            with self.assertRaises(PermissionError):await partners.submit(42,12,'fixture',b'cipher')

    async def test_other_shop_cannot_be_edited_or_moderated(self):
        for action in [lambda:partners.set_content(42,777002,'welcome','X'),lambda:partners.ban(42,777002,51,'X')]:
            with self.assertRaises(PermissionError):await action()

    async def test_handler_allowlist_is_narrow(self):
        handler=AsyncMock();event=NS(data='fixture')
        for module,name,allowed in [('handlers.user.shop','confirm_purchase',True),('handlers.navigation','cancel',True),('handlers.direct_support','user_message',True),('handlers.direct_support','admin_reply',False),('handlers.admin.manage','change_balance',False),('handlers.admin.advertising','campaigns',False),('handlers.userish.evil','test',False)]:
            async def callback():pass
            callback.__module__=module;callback.__name__=name
            with patch.object(runtime,'unavailable',AsyncMock()) as blocked:
                handler.reset_mock();await runtime.PartnerPermissions()(handler,event,{'handler':NS(callback=callback)})
                self.assertEqual(handler.await_count,1 if allowed else 0,(module,name))
                self.assertEqual(blocked.await_count,0 if allowed else 1)

    async def test_all_deposit_entries_use_main_funding(self):
        async def callback():pass
        callback.__module__='handlers.user.balance'
        handler=AsyncMock()
        with patch('handlers.partners.show_funding',AsyncMock()) as funding:
            for value in ('balance','topup_balance','deposit_crypto','deposit_stars','stars_buy:100'):
                await runtime.PartnerPermissions()(handler,NS(data=value),{'handler':NS(callback=callback)})
            self.assertEqual(funding.await_count,5);handler.assert_not_awaited()


class BotScopeTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.cur=NS(execute=AsyncMock())
        @asynccontextmanager
        async def transaction():yield self.cur
        self.p={'bot_id':777001,'owner_id':42,'status':'enabled','content_json':'{"welcome":"Partner"}'}
        for p in [patch.object(runtime,'MAIN',NS(id=123456,me=AsyncMock(return_value=NS(username='main_fixture_bot')))),patch.object(partners,'get',AsyncMock(return_value=self.p)),patch.object(partners,'banned',AsyncMock(return_value=False)),patch.object(runtime,'_transaction',transaction)]:
            p.start();self.addCleanup(p.stop)
        self.event=Update.model_validate({'update_id':1,'message':{'message_id':1,'date':0,'chat':{'id':42,'type':'private'},'from':{'id':42,'is_bot':False,'first_name':'Fixture'},'text':'/start'}})

    async def test_context_is_set_for_handler_and_restored_after_failure(self):
        before=CURRENT.get();content=CONTENT.get()
        async def handler(event,data):
            self.assertEqual(CURRENT.get()['bot_id'],777001);self.assertEqual(CONTENT.get()['welcome'],'Partner')
            raise RuntimeError('fixture')
        with self.assertRaises(RuntimeError):await runtime.BotScope()(handler,self.event,{'bot':NS(id=777001)})
        self.assertIs(CURRENT.get(),before);self.assertIs(CONTENT.get(),content)

    async def test_disabled_shop_drops_updates(self):
        self.p['status']='paused';handler=AsyncMock()
        await runtime.BotScope()(handler,self.event,{'bot':NS(id=777001)})
        handler.assert_not_awaited();self.cur.execute.assert_not_awaited()

    async def test_partner_successful_payment_never_enters_main_credit_handler(self):
        message=self.event.message.model_copy(update={'text':None,'successful_payment':NS()})
        event=self.event.model_copy(update={'message':message});handler=AsyncMock()
        await runtime.BotScope()(handler,event,{'bot':NS(id=777001)})
        handler.assert_not_awaited()


class PollingLifecycleTests(IsolatedAsyncioTestCase):
    async def test_approved_polling_delivers_updates_and_persists_offset(self):
        from unittest.mock import MagicMock
        p={'bot_id':777001,'token_cipher':b'FIXTURE','offset_id':10,'status':'enabled','lease_owner':'lease'}
        bot=NS(id=777001,delete_webhook=AsyncMock(),get_updates=AsyncMock(return_value=[NS(update_id=12)]),session=NS(middleware=MagicMock(),close=AsyncMock()))
        dp=NS(resolve_used_update_types=lambda:['message'],feed_update=AsyncMock());cur=NS(execute=AsyncMock())
        @asynccontextmanager
        async def transaction():yield cur
        with patch.object(runtime,'claim',AsyncMock(side_effect=[True,True,False])),patch.object(runtime,'Bot',return_value=bot),patch.object(runtime,'decrypt',return_value='fixture'),patch.object(partners,'get',AsyncMock(return_value=p)),patch.object(runtime,'_transaction',transaction):
            await runtime.poll(dp,p,'lease')
        dp.feed_update.assert_awaited_once_with(bot,bot.get_updates.return_value[0])
        bot.get_updates.assert_awaited_once_with(offset=10,timeout=20,allowed_updates=['message'])
        self.assertEqual(cur.execute.call_args_list[0].args[1],(13,777001,'lease'))
        bot.session.close.assert_awaited_once();self.assertNotIn(777001,runtime.CLIENTS)

    async def test_pause_drops_fetched_updates_before_dispatch(self):
        from unittest.mock import MagicMock
        p={'bot_id':777001,'token_cipher':b'FIXTURE','offset_id':10,'status':'paused','lease_owner':'lease'}
        bot=NS(id=777001,delete_webhook=AsyncMock(),get_updates=AsyncMock(return_value=[NS(update_id=12)]),session=NS(middleware=MagicMock(),close=AsyncMock()))
        dp=NS(resolve_used_update_types=lambda:['message'],feed_update=AsyncMock());cur=NS(execute=AsyncMock())
        @asynccontextmanager
        async def transaction():yield cur
        with patch.object(runtime,'claim',AsyncMock(return_value=True)),patch.object(runtime,'Bot',return_value=bot),patch.object(runtime,'decrypt',return_value='fixture'),patch.object(partners,'get',AsyncMock(return_value=p)),patch.object(runtime,'_transaction',transaction):
            await runtime.poll(dp,p,'lease')
        dp.feed_update.assert_not_awaited();bot.session.close.assert_awaited_once()
        self.assertEqual(cur.execute.await_count,1) # lease release only; offset retained
