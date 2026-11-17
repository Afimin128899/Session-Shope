"""Bot-only categorized navigation; existing action callbacks stay reachable."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from test_payments import config
from keyboards.admin_kb import get_admin_panel, ADMIN_CATEGORIES
from handlers.admin import admin_panel


def callbacks(menu):
    return {b.callback_data for row in menu.inline_keyboard for b in row if b.callback_data}


class BotAdminCategories(unittest.IsolatedAsyncioTestCase):
    def test_home_is_compact_and_every_category_opens(self):
        with patch('utils.miniapp.admin_miniapp_url', return_value=None):
            menu = get_admin_panel()
        self.assertEqual(len(menu.inline_keyboard), 6)
        self.assertEqual({c for c in callbacks(menu) if c.startswith('admin_category:')},
                         {'admin_category:'+name for name in ADMIN_CATEGORIES})

    def test_all_original_actions_remain_reachable_and_callback_size_is_valid(self):
        expected = {'expand_tools','shop_status','review_list:0','demo:open','spam_all','quality_discount',
                    'market_report','adm_search','adm_audit','add_account_telethon','add_account_session',
                    'admin_del_account','admin_accounts_list','admin_users','admin_balance_menu',
                    'admin_promos_menu','admin_prices_menu','admin_stats','admin_broadcast','admin_categories',
                    'admin_btn_editor','admin_sub_menu','admin_settings_menu','admin_maintenance',
                    'p:list','pedit:menu:0','p:main_ban','p:main_unban','helper_manage'}
        reachable = set()
        for key in ADMIN_CATEGORIES:
            menu = get_admin_panel(key)
            reachable |= callbacks(menu)
            self.assertTrue(all(len(row)<=2 for row in menu.inline_keyboard))
            self.assertEqual(menu.inline_keyboard[-1][0].callback_data, 'admin_home')
            for row in menu.inline_keyboard:
                for b in row:
                    self.assertLessEqual(len(b.callback_data.encode()),64)
                    if b.callback_data in {'admin_del_account','p:main_ban'}:
                        self.assertEqual(b.style,'danger')
        self.assertTrue(expected <= reachable)

    async def test_non_admin_cannot_open_any_category_or_clear_state(self):
        call=NS(from_user=NS(id=999),data='admin_category:inventory')
        state=NS(clear=AsyncMock())
        with patch.object(admin_panel,'is_admin',return_value=False),patch.object(admin_panel,'answer_safe',AsyncMock()) as answer,patch.object(admin_panel,'edit_message_safe',AsyncMock()) as edit:
            await admin_panel.admin_category(call,state)
            edit.assert_not_awaited();state.clear.assert_not_awaited()
            self.assertTrue(answer.call_args.kwargs['show_alert'])

    async def test_admin_category_clears_pending_form_and_uses_selected_keyboard(self):
        call=NS(from_user=NS(id=42),data='admin_category:inventory')
        state=NS(clear=AsyncMock())
        with patch.object(admin_panel,'is_admin',return_value=True),patch.object(admin_panel,'answer_safe',AsyncMock()),patch.object(admin_panel,'edit_message_safe',AsyncMock()) as edit:
            await admin_panel.admin_category(call,state)
            state.clear.assert_awaited_once()
            self.assertIn('admin_accounts_list',callbacks(edit.call_args.kwargs['reply_markup']))
            self.assertNotIn('admin_users',callbacks(edit.call_args.kwargs['reply_markup']))

    async def test_unknown_category_does_not_change_screen_or_state(self):
        call=NS(from_user=NS(id=42),data='admin_category:unknown')
        state=NS(clear=AsyncMock())
        with patch.object(admin_panel,'is_admin',return_value=True),patch.object(admin_panel,'answer_safe',AsyncMock()),patch.object(admin_panel,'edit_message_safe',AsyncMock()) as edit:
            await admin_panel.admin_category(call,state)
            state.clear.assert_not_awaited();edit.assert_not_awaited()
