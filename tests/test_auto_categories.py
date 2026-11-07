"""Automatic labels must never turn an unknown/temporary result into a promise."""
import unittest
from decimal import Decimal
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch
from test_payments import config
from database import auto_categories
from services.spam_check import classify_reply
from utils.commerce_policy import require_category


class CategoryTests(unittest.TestCase):
    def test_chile_categories_follow_each_confirmed_status(self):
        for status,label in [('clear','Без спамблока'),('permanent','Вечный спамблок'),('limited','Есть ограничения')]:
            value=auto_categories.specification('+56912345678',status)
            self.assertEqual(value['slug'],'auto-cl-'+status)
            self.assertEqual(value['name'],'Чили 🇨🇱 · '+label)
            self.assertEqual(value['active'],1)

    def test_unknown_errors_and_unchecked_are_hidden_and_never_called_clear(self):
        for status in ['unknown','error','not_checked','invented']:
            value=auto_categories.specification('+56912345678',status)
            self.assertEqual(value['slug'],'auto-cl-pending')
            self.assertEqual(value['active'],0)
            self.assertNotIn('Без спамблока',value['name'])

    def test_pending_category_cannot_be_manually_enabled_or_sold(self):
        with self.assertRaises(ValueError):require_category('auto-cl-pending')

    def test_country_policy_is_preserved_and_kazakhstan_is_recognized(self):
        for phone in ['+79991234567','+380501234567']:
            with self.assertRaises(ValueError):auto_categories.specification(phone,'clear')
        self.assertEqual(auto_categories.specification('+77001234567','clear')['slug'],'auto-kz-clear')
        self.assertEqual(auto_categories.specification('0056912345678','clear')['slug'],'auto-cl-clear')

    def test_manual_move_cannot_put_permanent_account_into_clear_category(self):
        with self.assertRaises(ValueError):auto_categories.validate_selection('+56912345678','permanent',datetime.now(),'auto-cl-clear')
        with self.assertRaises(ValueError):auto_categories.validate_selection('+56912345678','permanent',None,'auto-cl-permanent')
        auto_categories.validate_selection('+56912345678','permanent',datetime.now(),'auto-cl-permanent')
        with self.assertRaises(ValueError):auto_categories.validate_selection('+56912345678','unknown',datetime.now(),'us','auto-cl-pending')

    def test_only_explicit_permanent_replies_are_permanent(self):
        for body in ['Your account has been permanently limited.','Ваш аккаунт ограничен навсегда.','На Ваш аккаунт наложены бессрочные ограничения.']:
            self.assertEqual(classify_reply(body),'permanent')
        self.assertEqual(classify_reply('Your account is currently limited.'),'limited')
        self.assertEqual(classify_reply('No limits are currently applied to your account. Your account is permanently limited.'),'unknown')


class CategoryStorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_manually_hidden_stock_is_not_made_public_by_a_background_check(self):
        cur=NS(execute=AsyncMock(),fetchone=AsyncMock(return_value={'number':'+56912345678','country':'manual-disabled','is_active':0}))
        with patch.object(auto_categories,'ensure',AsyncMock()) as ensure:
            await auto_categories.move_checked(cur,1,'clear')
            ensure.assert_not_awaited()

    async def test_a_legacy_account_without_a_category_can_be_grouped(self):
        cur=NS(execute=AsyncMock(),fetchone=AsyncMock(return_value={'number':'+56912345678','country':None,'is_active':None}))
        with patch.object(auto_categories,'ensure',AsyncMock(return_value='auto-cl-clear')) as ensure:
            await auto_categories.move_checked(cur,1,'clear')
            ensure.assert_awaited_once_with(cur,'+56912345678','clear')
