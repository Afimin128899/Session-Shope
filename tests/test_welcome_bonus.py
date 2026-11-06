"""Welcome credit must be tied to the verified visitor and share signup atomicity."""
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import unittest

from test_payments import db, config
import test_miniapp
from database import welcome, referrals
from handlers.user import start
from utils import nav
from miniapp import server


class RegistrationTests(unittest.IsolatedAsyncioTestCase):
    setUp = test_miniapp.CheckoutTests.setUp

    async def test_old_user_never_gets_a_backfilled_bonus_or_new_referral(self):
        self.cur.rowcount=0
        with patch.object(welcome,'credit_new_user',AsyncMock()) as credit:
            self.assertEqual(await referrals.register_user(42,43,'renamed'),0)
            credit.assert_not_awaited()
        self.conn.commit.assert_awaited_once()
        self.assertFalse(any('INSERT INTO referrals' in c.args[0] for c in self.cur.execute.call_args_list))

    async def test_failed_welcome_audit_rolls_back_user_credit_and_receipt(self):
        self.cur.rowcount=1
        with patch.object(welcome,'_record',AsyncMock(side_effect=OSError('fixture failure'))):
            with self.assertRaises(OSError):await referrals.register_user(42,None)
        self.conn.rollback.assert_awaited_once();self.conn.commit.assert_not_awaited()

    async def test_administrative_creation_does_not_grant_login_money(self):
        with patch.object(referrals,'register_user',AsyncMock(return_value=0)) as register:
            await db.create_user(42,'manual')
            register.assert_awaited_once_with(42,None,'manual',welcome_bonus=False)

    async def test_callback_navigation_registers_the_actual_visitor(self):
        with patch.object(nav,'create_user',AsyncMock()) as register:
            await nav.ensure_user(42,'visitor')
            register.assert_awaited_once_with(42,'visitor',welcome_bonus=True)

    async def test_invalid_payer_ids_never_start_a_signup_transaction(self):
        for value in [True,-1,0,'42',9223372036854775808]:
            with self.assertRaises(ValueError):await referrals.register_user(value,None)
        self.conn.begin.assert_not_awaited()


class BotWelcomeTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_announces_the_real_committed_bonus_only_once(self):
        message=NS(from_user=NS(id=42,username='visitor',first_name='Guest'),answer=AsyncMock())
        with patch.object(start,'is_new_user',AsyncMock(return_value=True)),patch.object(start,'create_user_with_referrer',AsyncMock(side_effect=[Decimal(4),Decimal(0)])),patch.object(start,'update_user_username',AsyncMock()),patch.object(start,'main_menu',AsyncMock(return_value=None)),patch.object(start,'answer_screen',AsyncMock()):
            await start.cmd_start(message,NS(args=None));await start.cmd_start(message,NS(args=None))
        message.answer.assert_awaited_once()
        self.assertIn('4.00 ₽',message.answer.call_args.args[0])


class WelcomeAPITests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_miniapp.MiniAppAPITests.asyncSetUp
    asyncTearDown=test_miniapp.MiniAppAPITests.asyncTearDown

    async def test_profile_uses_verified_id_and_reports_the_recorded_credit(self):
        with patch.object(welcome,'received',AsyncMock(return_value=Decimal(4))) as received,patch.object(db,'create_user',AsyncMock()) as register:
            response=await self.client.get('/api/me?user_id=99&welcome_bonus=100',headers=self.headers)
            self.assertEqual(response.status,200);self.assertEqual((await response.json())['welcome_bonus'],'4')
            received.assert_awaited_once_with(42)
            register.assert_awaited_once_with(42,'alex_test',welcome_bonus=True)

    async def test_unsigned_requests_cannot_register_or_credit_a_user(self):
        with patch.object(db,'create_user',AsyncMock()) as register:
            response=await self.client.get('/api/me?user_id=42')
            self.assertEqual(response.status,401);register.assert_not_awaited()
