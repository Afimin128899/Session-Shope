"""Fake Telegram protocol responses: no network or usable account sessions."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

from telethon import errors, types, functions
from services.admin_session_workbench.telegram import migrate, read_code, Source, UserFacingError, make_client


class Client(NS):
    async def __call__(self, request):
        return True


def fake():
    return Client(is_user_authorized=AsyncMock(return_value=True),
                  get_me=AsyncMock(return_value=NS(id=123, phone='15551112222', deleted=False)),
                  get_entity=AsyncMock(side_effect=lambda peer:NS(id=777000 if peer == 777000 else 9001)),
                  get_messages=AsyncMock(return_value=[NS(id=10)]), send_code_request=AsyncMock(), sign_in=AsyncMock())


def sent(kind=None, **kwargs):
    return types.auth.SentCode(kind or types.auth.SentCodeTypeApp(5), 'private-hash', **kwargs)


class AdminSessionProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_sms_uses_manual_input_without_reading_codes(self):
        old, new = fake(), fake()
        old.iter_messages = AsyncMock(side_effect=AssertionError('SMS must not be read from app'))
        new.send_code_request.return_value = sent(types.auth.SentCodeTypeSms(5))
        ask = AsyncMock(return_value='12345')
        await migrate(old, new, ask, AsyncMock(), {})
        ask.assert_awaited_once()
        old.iter_messages.assert_not_called()
        self.assertEqual(new.sign_in.call_args.kwargs['phone'], '+15551112222')
        self.assertEqual(new.sign_in.call_args.kwargs['code'], '12345')

    async def test_json_and_manual_2fa_complete_new_authorization(self):
        for saved in (True, False):
            old, new = fake(), fake()
            new.send_code_request.return_value = sent(types.auth.SentCodeTypeSms(5))
            new.sign_in.side_effect = [errors.SessionPasswordNeededError(None), None]
            await migrate(old, new, AsyncMock(side_effect=['12345','manual-password']), AsyncMock(),
                          {'password':'saved-password'} if saved else {})
            self.assertEqual(new.sign_in.call_args.kwargs['password'], 'saved-password' if saved else 'manual-password')

    async def test_separate_message_boundaries_ignore_host_clock(self):
        old = fake()
        seen = []
        async def messages(peer, min_id, limit):
            seen.append((peer, min_id))
            if peer == 9001:
                yield NS(id=3, out=False, date='1900-01-01', raw_text='Login code: 12345')
        old.iter_messages = messages
        code, _ = await read_code(old, [Source(777000,100,'a'),Source(9001,2,'b')], 5)
        self.assertEqual(code,'12345')
        self.assertEqual(seen,[(777000,100),(9001,2)])

    async def test_completed_authorization_does_not_request_manual_code(self):
        old, new = fake(), fake()
        new.send_code_request.return_value = types.auth.SentCodeSuccess(types.auth.Authorization(types.User(id=123)))
        ask = AsyncMock()
        await migrate(old,new,ask,AsyncMock(),{})
        ask.assert_not_awaited()
        new.sign_in.assert_not_awaited()

    async def test_flood_wait_propagates_without_request_retry(self):
        old, new = fake(), fake()
        new.send_code_request.side_effect = errors.FloodWaitError(None,capture=60)
        with self.assertRaises(errors.FloodWaitError):
            await migrate(old,new,AsyncMock(),AsyncMock(),{})
        self.assertEqual(new.send_code_request.await_count,1)

    async def test_one_resend_waits_for_timeout_and_refreshes_boundaries(self):
        old, new = fake(), fake()
        new.send_code_request.return_value = sent(types.auth.SentCodeTypeSms(5),next_type=types.auth.CodeTypeSms(),timeout=20)
        requests = []
        class ResendClient(Client):
            async def __call__(self, request):
                requests.append(request)
                self_assert.assertIsInstance(request,functions.auth.ResendCodeRequest)
                self_assert.assertEqual(old.get_messages.await_count,4)
                return sent(types.auth.SentCodeTypeSms(5))
        self_assert = self
        resend = ResendClient(**vars(new))
        sleep = AsyncMock()
        await migrate(old,resend,AsyncMock(side_effect=['resend','12345']),AsyncMock(),{},sleep=sleep)
        sleep.assert_awaited_once_with(20)
        self.assertEqual(len(requests),1)

    async def test_cancel_during_manual_input_does_not_sign_in(self):
        old, new = fake(), fake()
        new.send_code_request.return_value = sent(types.auth.SentCodeTypeSms(5))
        started = asyncio.Event()
        async def ask(*args):
            started.set()
            await asyncio.Event().wait()
        task = asyncio.create_task(migrate(old,new,ask,AsyncMock(),{}))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        new.sign_in.assert_not_awaited()


class LoginProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_login_progress_is_emitted_before_sign_in_and_confirmation_after(self):
        old,new = fake(),fake()
        new.send_code_request.return_value = sent(types.auth.SentCodeTypeSms(5))
        events = []
        async def report(text):
            events.append(text)
        async def signin(**kwargs):
            self.assertEqual(events[-1],'Вход в новую авторизацию')
            events.append('actual-sign-in')
        new.sign_in.side_effect = signin
        await migrate(old,new,AsyncMock(return_value='12345'),report,{})
        self.assertLess(events.index('Вход в новую авторизацию'),events.index('actual-sign-in'))
        self.assertLess(events.index('actual-sign-in'),events.index('Новая авторизация подтверждена'))


class ControlledRequestTests(unittest.IsolatedAsyncioTestCase):
    """Exercise Telethon's real _call loop; only the network sender is fake."""

    async def asyncSetUp(self):
        self.directory = TemporaryDirectory()
        self.client = make_client(Path(self.directory.name) / 'new.session', {}, 12345, '0' * 32)
        self.original_sender = self.client._sender
        self.client.session.set_dc(2, '149.154.167.51', 443)
        self.client.is_user_authorized = AsyncMock(return_value=False)

        async def switch(dc):
            self.client.session.set_dc(dc, '149.154.167.51', 443)
        self.client._switch_dc = AsyncMock(side_effect=switch)

    async def asyncTearDown(self):
        self.client._sender = self.original_sender
        await self.client.disconnect()
        self.directory.cleanup()

    def sender(self, *responses):
        def send(request, **kwargs):
            response = next(results)
            future = asyncio.get_running_loop().create_future()
            if isinstance(response, Exception):
                future.set_exception(response)
            else:
                future.set_result(response)
            return future
        results = iter(responses)
        sender = NS(send=Mock(side_effect=send))
        self.client._sender = sender
        return sender

    async def test_each_dc_redirect_continues_once_after_actual_telethon_switch(self):
        for error in (errors.PhoneMigrateError, errors.NetworkMigrateError, errors.UserMigrateError):
            with self.subTest(error=error.__name__):
                self.client.session.set_dc(2, '149.154.167.51', 443)
                self.client._switch_dc.reset_mock()
                result = sent()
                sender = self.sender(error(None, capture=4), result)
                self.assertIs(await self.client.send_code_request('+15551112222'), result)
                self.client._switch_dc.assert_awaited_once_with(4)
                self.assertEqual(sender.send.call_count, 2)
                requests = [call.args[0] for call in sender.send.call_args_list]
                self.assertTrue(all(isinstance(r, functions.auth.SendCodeRequest) for r in requests))
                self.assertIs(requests[0], requests[1])

    async def test_repeated_dc_redirect_is_bounded(self):
        sender = self.sender(errors.PhoneMigrateError(None, capture=4),
                             errors.PhoneMigrateError(None, capture=5))
        with self.assertRaisesRegex(UserFacingError, 'повторно сменил дата-центр'):
            await self.client.send_code_request('+15551112222')
        self.assertEqual(sender.send.call_count, 2)

    async def test_flood_after_redirect_is_not_retried(self):
        sender = self.sender(errors.PhoneMigrateError(None, capture=4),
                             errors.FloodWaitError(None, capture=60))
        with self.assertRaises(errors.FloodWaitError) as raised:
            await self.client.send_code_request('+15551112222')
        self.assertEqual(raised.exception.seconds, 60)
        self.assertEqual(sender.send.call_count, 2)

    async def test_other_errors_are_preserved_without_automatic_resend(self):
        for error in (errors.FloodWaitError(None, capture=60), errors.AuthRestartError(None),
                      errors.ServerError(None, 'internal'), asyncio.TimeoutError()):
            with self.subTest(error=type(error).__name__):
                self.client._flood_waited_requests.clear()
                sender = self.sender(error)
                with patch('telethon.client.users.asyncio.sleep', new_callable=AsyncMock):
                    with self.assertRaises(type(error)):
                        await self.client.send_code_request('+15551112222')
                self.assertEqual(sender.send.call_count, 1)

    async def test_successful_request_is_sent_once(self):
        result = sent()
        sender = self.sender(result)
        self.assertIs(await self.client.send_code_request('+15551112222'), result)
        self.assertEqual(sender.send.call_count, 1)

    async def test_authorized_client_redirect_is_not_forced(self):
        self.client.is_user_authorized.return_value = True
        sender = self.sender(errors.PhoneMigrateError(None, capture=4))
        with self.assertRaises(errors.PhoneMigrateError):
            await self.client.send_code_request('+15551112222')
        self.client._switch_dc.assert_not_awaited()
        self.assertEqual(sender.send.call_count, 1)
