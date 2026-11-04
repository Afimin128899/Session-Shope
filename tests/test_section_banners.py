"""Navigation media regressions; no Telegram, providers or production database."""
import os
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from test_payments import config  # Install fake config before importing navigation.
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.methods import EditMessageMedia
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from utils import nav, section_banners as art


class BannerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        art._photos.clear()
        self.addCleanup(art._photos.clear)
        self.photo = NS(file_id='public-image-42', file_unique_id='unique-42')
        self.result = NS(photo=[self.photo])
        self.message = NS(bot=NS(id=123), photo=None, edit_text=AsyncMock(),
                          edit_media=AsyncMock(return_value=self.result), edit_caption=AsyncMock(),
                          answer=AsyncMock(), answer_photo=AsyncMock(return_value=self.result), delete=AsyncMock())
        self.call = NS(data='buy', message=self.message)
        self.keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text='В профиль', callback_data='my_profile'),
        ]])

    async def test_section_navigation_adds_media_and_keeps_caption_and_buttons(self):
        await nav.edit_message_safe(self.call, '<b>Каталог</b> &amp; цены', reply_markup=self.keyboard)
        args = self.message.edit_media.call_args.kwargs
        self.assertIsInstance(args['media'].media, FSInputFile)
        self.assertEqual(args['media'].caption, '<b>Каталог</b> &amp; цены')
        self.assertEqual(args['media'].parse_mode, 'HTML')
        self.assertEqual(args['reply_markup'], self.keyboard)
        self.message.edit_text.assert_not_awaited()
        self.message.delete.assert_not_awaited()

    async def test_same_banner_updates_caption_and_other_section_reuses_telegram_file(self):
        await nav.edit_message_safe(self.call, 'Каталог')
        self.message.photo = [self.photo]
        await nav.edit_message_safe(self.call, 'Другая страница', reply_markup=self.keyboard)
        self.message.edit_caption.assert_awaited_once_with(caption='Другая страница', parse_mode='HTML', reply_markup=self.keyboard)
        # Return from a different screen: cached ID, not another file upload.
        self.message.photo = [NS(file_unique_id='other')]
        await nav.edit_message_safe(self.call, 'Каталог снова')
        self.assertEqual(self.message.edit_media.call_args.kwargs['media'].media, self.photo.file_id)

    async def test_custom_home_replacement_invalidates_cached_file(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(art, 'ROOT', Path(folder)):
            path = Path(folder) / 'assets/welcome.png'
            path.parent.mkdir()
            path.write_bytes(b'first image')
            await art.answer_screen(self.message, 'Меню', section='home')
            await art.answer_screen(self.message, 'Меню', section='home')
            self.assertEqual(self.message.answer_photo.call_args.args[0], self.photo.file_id)
            path.write_bytes(b'new image content')
            await art.answer_screen(self.message, 'Меню', section='home')
            self.assertIsInstance(self.message.answer_photo.call_args.args[0], FSInputFile)

    async def test_long_html_caption_switches_to_complete_text_without_truncation(self):
        # Count after parsing HTML; long URLs/tags alone do not consume caption space.
        self.assertTrue(art.caption_fits('<b>' + 'я' * 1024 + '</b>'))
        self.assertTrue(art.caption_fits('&amp;' * 1024))
        self.assertFalse(art.caption_fits('⭐' * 1025))
        self.assertFalse(art.caption_fits('😀' * 513))
        text = '<b>Описание</b>\n' + 'я' * 1500
        self.message.photo = [self.photo]
        await nav.edit_message_safe(self.call, text, reply_markup=self.keyboard)
        self.message.answer.assert_awaited_once_with(text, reply_markup=self.keyboard, parse_mode='HTML')
        self.message.delete.assert_awaited_once()
        self.message.edit_media.assert_not_awaited()

    async def test_failed_replacement_never_deletes_previous_screen(self):
        self.message.edit_media.side_effect = TelegramBadRequest(EditMessageMedia(media={
            'type': 'photo', 'media': 'test',
        }), "Bad Request: message can't be edited")
        self.message.answer_photo.side_effect = OSError('offline')
        with self.assertRaises(OSError):
            await nav.edit_message_safe(self.call, 'Каталог')
        self.message.delete.assert_not_awaited()

    async def test_bad_html_never_hides_error_or_sends_duplicate_screen(self):
        self.message.edit_media.side_effect = TelegramBadRequest(EditMessageMedia(media={
            'type': 'photo', 'media': 'test',
        }), "Bad Request: can't parse entities")
        with self.assertRaises(TelegramBadRequest):
            await nav.edit_message_safe(self.call, '<b>invalid')
        self.message.answer_photo.assert_not_awaited()
        self.message.delete.assert_not_awaited()

    async def test_no_change_is_success_and_short_flood_wait_retries_media_only(self):
        method = EditMessageMedia(media={'type': 'photo', 'media': 'test'})
        self.message.edit_media.side_effect = TelegramBadRequest(method, 'Bad Request: message is not modified')
        await nav.edit_message_safe(self.call, 'Каталог')
        self.message.answer_photo.assert_not_awaited()
        self.message.edit_media.reset_mock()
        self.message.edit_media.side_effect = [TelegramRetryAfter(method, 'wait', retry_after=1), self.result]
        with patch.object(nav.asyncio, 'sleep', AsyncMock()) as wait:
            await nav.edit_message_safe(self.call, 'Каталог')
        wait.assert_awaited_once_with(1)
        self.assertEqual(self.message.edit_media.await_count, 2)

    async def test_missing_banner_is_plain_text_and_paths_do_not_depend_on_cwd(self):
        with patch.object(art, 'ROOT', Path('/nonexistent-sband-banners')):
            await art.answer_screen(self.message, 'Меню', section='home', reply_markup=self.keyboard)
        self.message.answer.assert_awaited_once()
        self.message.answer_photo.assert_not_awaited()
        before = Path.cwd()
        try:
            os.chdir('/tmp')
            self.assertTrue(art.banner_for('home').path.is_file())
        finally:
            os.chdir(before)
        self.assertIsNone(art.banner_for('../.env'))

    def test_customer_and_admin_entries_have_valid_telegram_sized_generated_images(self):
        # PNG metadata only: validate shipped assets without adding image dependencies.
        for section in art.SECTIONS:
            with self.subTest(section=section):
                path = art.banner_for(section).path
                header = path.read_bytes()[:24]
                self.assertEqual(header[:8], b'\x89PNG\r\n\x1a\n')
                width, height = struct.unpack('>II', header[16:24])
                self.assertGreater(width, height)
                self.assertLess(width + height, 10000)
                self.assertLess(path.stat().st_size, 10 * 1024 * 1024)
        for callback in ('back_main', 'buy', 'buy_acc:1', 'my_profile', 'wheel', 'deposit_stars',
                         'my_purchases', 'tk_user:0', 'admin_panel_button', 'admin_stats',
                         'admin_balance_menu', 'admin_categories', 'admin_users', 'admin_broadcast',
                         'admin_promos_menu', 'admin_btn_editor', 'spam_all', 'demo:open'):
            with self.subTest(callback=callback):
                self.assertIn(art.section_for_callback(callback), art.SECTIONS)
        self.assertIsNone(art.section_for_callback('unrelated_action'))


if __name__ == '__main__':
    unittest.main()
