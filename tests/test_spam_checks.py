"""Offline SpamBot tests. No real sessions, outbound messages or Telegram calls."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from test_payments import config
import test_miniapp
from services import spam_check
from database import spam_checks
from miniapp import server, storage
from handlers.admin import spam_checks as ui
from telethon.errors import FloodWaitError

CLEAR = 'Good news, no limits are currently applied to your account. You’re free as a bird!'
LIMITED = 'Unfortunately, your account has been limited until tomorrow.'


class ReplyTests(unittest.TestCase):
    def test_positive_clear_responses_and_explicit_limits(self):
        for text in (CLEAR, 'Отличные новости! На Ваш аккаунт не наложено никаких ограничений.', 'Ваш аккаунт не ограничен.'):
            self.assertEqual(spam_check.classify_reply(text), 'clear')
        for text in (LIMITED, 'К сожалению, на Ваш аккаунт наложены временные ограничения.', 'Вашему аккаунту было назначено временное ограничение до завтра.'):
            self.assertEqual(spam_check.classify_reply(text), 'limited')

    def test_unrecognized_challenge_or_ambiguous_reply_is_never_clear(self):
        for text in ('', 'Please solve a CAPTCHA', 'No problems?', 'Unexpected language', CLEAR + ' Your account is currently limited.'):
            self.assertEqual(spam_check.classify_reply(text), 'unknown')

    def test_public_status_has_timestamp_but_no_session_reply_or_lease_token(self):
        result = spam_checks.public({'spam_status':'clear','spam_checked_at':datetime(2026,1,1), 'spam_token':'PRIVATE', 'data':'SESSION', 'spam_reason':'timeout'})
        self.assertEqual(result['checked_at'], '2026-01-01T00:00:00+00:00')
        self.assertNotIn('PRIVATE', str(result))
        self.assertNotIn('SESSION', str(result))
        self.assertNotIn('spam_reason', result)
        self.assertEqual(spam_checks.public({})['status'], 'not_checked')


class CallableClient(NS):
    def __call__(self, request):
        return self.unblock(request)


class ConversationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.sent=NS(id=10)
        self.dialog=NS(send_message=AsyncMock(return_value=self.sent), get_response=AsyncMock(return_value=NS(id=11,sender_id=100,raw_text=CLEAR)))
        context=MagicMock()
        context.__aenter__.return_value=self.dialog
        self.client=CallableClient(unblock=AsyncMock(),connect=AsyncMock(),disconnect=AsyncMock(),is_user_authorized=AsyncMock(return_value=True),
                       get_me=AsyncMock(return_value=NS(id=9001,phone='79990001122')),
                       get_entity=AsyncMock(return_value=NS(id=100,bot=True,username='SpamBot')),
                       conversation=MagicMock(return_value=context))
        patcher=patch.object(spam_check,'create_client',return_value=self.client)
        patcher.start();self.addCleanup(patcher.stop)

    async def check(self, **kwargs):
        return await spam_check.check_session('fixture-session-'*20, expected_id=kwargs.get('expected_id',9001), expected_phone=kwargs.get('expected_phone','+79990001122'))

    async def test_only_start_to_verified_username_and_fresh_reply(self):
        self.assertEqual((await self.check())['status'],'clear')
        self.client.get_entity.assert_awaited_once_with('SpamBot')
        self.dialog.send_message.assert_awaited_once_with('/start')
        self.dialog.get_response.assert_awaited_once_with(self.sent)
        self.client.disconnect.assert_awaited_once()

    async def test_limited_reply_is_reported_without_storing_its_body(self):
        self.dialog.get_response.return_value.raw_text=LIMITED
        result=await self.check()
        self.assertEqual(result['status'],'limited')
        self.assertNotIn(LIMITED,str(result))

    async def test_wrong_peer_never_receives_messages(self):
        self.client.get_entity.return_value=NS(id=100,bot=True,username='OtherBot')
        self.assertEqual((await self.check())['reason'],'wrong_peer')
        self.dialog.send_message.assert_not_awaited()

    async def test_mismatched_owner_or_phone_never_sends_start(self):
        for params in ({'expected_id':9002},{'expected_phone':'+71111111111'}):
            self.assertEqual((await self.check(**params))['reason'],'identity_mismatch')
        self.dialog.send_message.assert_not_awaited()

    async def test_revoked_session_does_not_read_spambot(self):
        self.client.is_user_authorized.return_value=False
        self.assertEqual((await self.check())['reason'],'unauthorized')
        self.client.get_entity.assert_not_awaited()

    async def test_history_or_wrong_sender_cannot_be_accepted_as_clear(self):
        for reply in (NS(id=9,sender_id=100,raw_text=CLEAR),NS(id=11,sender_id=101,raw_text=CLEAR)):
            self.dialog.get_response.return_value=reply
            self.assertEqual((await self.check())['status'],'unknown')

    async def test_unknown_reply_unblocks_and_retries_with_a_new_response(self):
        self.dialog.send_message.side_effect=[NS(id=10),NS(id=20)]
        self.dialog.get_response.side_effect=[NS(id=11,sender_id=100,raw_text='Please choose a language'),NS(id=21,sender_id=100,raw_text='Your account is permanently limited.')]
        report=await self.check()
        self.assertEqual(report['status'],'permanent')
        self.client.unblock.assert_awaited_once()
        self.assertEqual(self.dialog.send_message.await_count,2)
        self.assertEqual(self.dialog.get_response.call_args.args[0].id,20)

    async def test_repeated_unknown_is_never_reported_as_clear_or_retried_forever(self):
        self.dialog.get_response.return_value.raw_text='Unexpected new response'
        report=await self.check()
        self.assertEqual(report['status'],'unknown')
        self.assertEqual(self.dialog.send_message.await_count,2)
        self.client.unblock.assert_awaited_once()

    async def test_timeout_has_error_status_and_disconnects(self):
        self.dialog.get_response.side_effect=TimeoutError()
        self.assertEqual((await self.check())['reason'],'timeout')
        self.client.disconnect.assert_awaited_once()

    async def test_flood_wait_preserves_telegram_retry_delay(self):
        self.dialog.send_message.side_effect=FloodWaitError(request=None,capture=1800)
        report=await self.check()
        self.assertEqual(report,{'status':'error','reason':'flood_wait','retry_after':1800})

    async def test_exception_text_and_private_input_are_not_returned(self):
        self.client.connect.side_effect=OSError('PRIVATE_SESSION_AND_TOKEN')
        report=await self.check()
        self.assertEqual(report['status'],'error')
        self.assertNotIn('PRIVATE_SESSION_AND_TOKEN',str(report))

    async def test_cancellation_disconnects_and_propagates(self):
        self.dialog.get_response.side_effect=asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError): await self.check()
        self.client.disconnect.assert_awaited_once()


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_releases_lease_on_shutdown(self):
        lease={'id':1,'data':'fixture','number':'+7999','telegram_user_id':42}
        with patch.object(spam_checks,'claim',AsyncMock(return_value=lease)), \
             patch.object(spam_check,'check_session',AsyncMock(side_effect=asyncio.CancelledError())), \
             patch.object(spam_checks,'release',AsyncMock()) as release:
            with self.assertRaises(asyncio.CancelledError): await spam_check.spam_worker(None)
        release.assert_awaited_once_with(lease)

    async def test_flood_wait_is_not_shortened_and_finish_is_bound_to_same_session(self):
        cur=NS(execute=AsyncMock(),rowcount=1)
        @asynccontextmanager
        async def transaction(): yield cur
        lease={'id':1,'token':'lease-token','data':'session-private'}
        with patch.object(spam_checks,'_transaction',transaction), patch('database.auto_categories.move_checked',AsyncMock()):
            self.assertTrue(await spam_checks.finish(lease,{'status':'error','reason':'flood_wait','retry_after':7200}))
        self.assertEqual(cur.execute.call_args.args[1],('error','flood_wait',7200,1,'lease-token','session-private'))

    async def test_non_admin_cannot_queue_or_read_private_account(self):
        call=NS(from_user=NS(id=999),data='spam_check:1')
        with patch.object(ui,'ADMIN_IDS',[7]), patch.object(ui.db,'get_account',AsyncMock()) as account, \
             patch.object(spam_checks,'enqueue',AsyncMock()) as enqueue, patch.object(ui,'answer_safe',AsyncMock()):
            await ui.one_account(call)
            call.data='spam_all_yes'
            await ui.all_accounts(call)
        enqueue.assert_not_awaited();account.assert_not_awaited()


class SpamCheckoutTests(unittest.IsolatedAsyncioTestCase):
    setUp=test_miniapp.CheckoutTests.setUp

    async def test_active_check_cannot_be_sold(self):
        self.cur.fetchone.return_value={'id':1,'price':100,'country':'us','spam_running':True}
        with self.assertRaisesRegex(storage.CheckoutError,'проверка'):
            await storage.checkout(42,1,Decimal(100))
        self.conn.rollback.assert_awaited_once()
        self.assertEqual(self.cur.execute.await_count,1)

    async def test_changed_spam_status_requires_new_confirmation(self):
        self.cur.fetchone.return_value={'id':1,'price':100,'country':'us','spam_status':'limited'}
        with self.assertRaisesRegex(storage.CheckoutError,'изменился'):
            await storage.checkout(42,1,Decimal(100),spam_status='clear')
        self.conn.rollback.assert_awaited_once()
        self.assertEqual(self.cur.execute.await_count,1)


class SpamAPITests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_miniapp.MiniAppAPITests.asyncSetUp
    asyncTearDown=test_miniapp.MiniAppAPITests.asyncTearDown

    async def test_customer_cannot_queue_background_checks(self):
        with patch.object(config,'ADMIN_IDS',[7]),patch.object(spam_checks,'enqueue',AsyncMock()) as enqueue:
            for path in ('/api/admin/spam-checks','/api/admin/stock/1/spam-check'):
                response=await self.client.post(path,headers=self.headers,json={})
                self.assertEqual(response.status,403)
            enqueue.assert_not_awaited()

    async def test_admin_queue_uses_signed_user_and_validated_product(self):
        with patch.object(config,'ADMIN_IDS',[42]),patch.object(spam_checks,'enqueue',AsyncMock(return_value=1)) as enqueue:
            response=await self.client.post('/api/admin/stock/5/spam-check',headers=self.headers,json={'user_id':99})
            self.assertEqual(response.status,200)
            enqueue.assert_awaited_once_with(42,5)

    async def test_malformed_spam_quote_never_reaches_checkout(self):
        with patch.object(storage,'checkout_cart',AsyncMock()) as checkout:
            for status in ('invalid',[],True):
                response=await self.client.post('/api/cart/checkout',headers=self.headers,json={'items':[{'account_id':1,'price':'100','spam_status':status}]})
                self.assertEqual(response.status,400)
            checkout.assert_not_awaited()
