"""Maintenance preview is read-only; recovery, help and receipts remain available."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch

from test_payments import db
from database import shop_control
from handlers.admin import shop_control as admin
from utils.maintenance import maintenance_keyboard
from utils.section_banners import caption_fits
from utils.i18n import LANGUAGE


class MaintenanceInterfaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_preview_is_admin_only_and_does_not_change_settings(self):
        call=NS(from_user=NS(id=42),answer=AsyncMock());state=NS(clear=AsyncMock())
        values={'maintenance_mode':'0','maintenance_reason':'Обновление','maintenance_eta':'Сегодня, 18:00 МСК'}
        with patch.object(admin,'ADMIN_IDS',[42]),patch.object(admin.admin_web,'settings',AsyncMock(return_value=values)),patch.object(admin.admin_web,'save_settings',AsyncMock()) as save,patch.object(admin,'edit_message_safe',AsyncMock()) as edit:
            await admin.preview_maintenance(call,state)
            save.assert_not_awaited()
        self.assertEqual(edit.call_args.args[1],shop_control.maintenance_message(values))
        buttons=[b.callback_data for row in edit.call_args.kwargs['reply_markup'].inline_keyboard for b in row]
        self.assertEqual(buttons,['maintenance_preview','shop_status'])
        with patch.object(admin,'ADMIN_IDS',[]),patch.object(admin.admin_web,'settings',AsyncMock()) as read:
            await admin.preview_maintenance(call,state);read.assert_not_awaited()

    async def test_admin_panel_keeps_all_existing_switches_and_notice_editors(self):
        call=NS(from_user=NS(id=42),answer=AsyncMock());state=NS(clear=AsyncMock())
        with patch.object(admin,'ADMIN_IDS',[42]),patch.object(admin.admin_web,'settings',AsyncMock(return_value={})),patch.object(admin,'edit_message_safe',AsyncMock()) as edit:
            await admin.show_shop_control(call,state)
        callbacks={b.callback_data for row in edit.call_args.kwargs['reply_markup'].inline_keyboard for b in row}
        self.assertTrue({'shop_mode:maintenance','shop_mode:sales','shop_notice:maintenance_reason','shop_notice:maintenance_eta','shop_notice:sales_pause_reason','maintenance_preview','review_list:0','admin_home'}<=callbacks)

    async def test_buyer_status_keyboard_keeps_recovery_support_information_and_language(self):
        markup=maintenance_keyboard()
        self.assertEqual({b.callback_data for row in markup.inline_keyboard for b in row},{'check_maintenance','support','info_menu','language'})
        self.assertEqual(markup.inline_keyboard[0][0].style,'primary')

    async def test_notice_escapes_operator_text_and_fits_existing_banner(self):
        token=LANGUAGE.set('ru')
        try:
            text=shop_control.maintenance_message({'maintenance_reason':'<script>bad</script>','maintenance_eta':'<b>18:00</b>'})
            self.assertIn('&lt;script&gt;',text);self.assertNotIn('<script>',text)
            self.assertIn('&lt;b&gt;18:00&lt;/b&gt;',text)
            self.assertIn('Повторно оплачивать тот же счёт не нужно',text)
            self.assertTrue(caption_fits(text))
        finally: LANGUAGE.reset(token)
