"""Offline checks for Telegram keyboard decoration and sticker-pack failures."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_payments import db  # Install isolated config before importing keyboards.
from aiogram.methods import EditMessageReplyMarkup, SendMessage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from keyboards import user_kb
from utils import button_icons as icons


def keyboard(*buttons):
    return InlineKeyboardMarkup(inline_keyboard=[list(buttons)])


class ButtonIconsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        state = patch.dict(icons.PACK_ICONS, {}, clear=True)
        state.start()
        self.addCleanup(state.stop)

    async def test_pack_name_and_real_ids_are_used_with_variation_selectors(self):
        bot = SimpleNamespace(get_sticker_set=AsyncMock(return_value=SimpleNamespace(stickers=[
            SimpleNamespace(emoji='💬', custom_emoji_id='1001'),
            SimpleNamespace(emoji='✍️', custom_emoji_id='1002'),
            SimpleNamespace(emoji='⬅️', custom_emoji_id='1003'),
            SimpleNamespace(emoji='📊', custom_emoji_id=None),
        ])))
        self.assertTrue(await icons.load_pack(bot))
        bot.get_sticker_set.assert_awaited_once_with(name='tgmacicons')
        self.assertEqual(icons.icon_for('support'), '1001')
        self.assertEqual(icons.icon_for('edit'), '1002')
        self.assertEqual(icons.icon_for('back'), '1003')
        self.assertEqual(icons.icon_for('stats'), icons.FALLBACK['stats'])

    async def test_unavailable_pack_keeps_defaults_and_does_not_log_exception_secrets(self):
        bot = SimpleNamespace(get_sticker_set=AsyncMock(side_effect=OSError('token-bearing-url')))
        with self.assertLogs(icons.logger, level='WARNING') as logs:
            self.assertFalse(await icons.load_pack(bot))
        self.assertNotIn('token-bearing-url', ''.join(logs.output))
        self.assertEqual(icons.icon_for('support'), icons.FALLBACK['support'])

    async def test_unsuitable_pack_does_not_replace_previously_loaded_icons(self):
        icons.PACK_ICONS['support'] = '1001'
        bot = SimpleNamespace(get_sticker_set=AsyncMock(return_value=SimpleNamespace(stickers=[])))
        with self.assertLogs(icons.logger, level='WARNING'):
            self.assertFalse(await icons.load_pack(bot))
        self.assertEqual(icons.icon_for('support'), '1001')

    async def test_customer_menu_has_support_icon_and_keeps_existing_custom_icons(self):
        icons.PACK_ICONS['support'] = '1001'
        with patch.object(user_kb, 'get_button_label', AsyncMock(return_value=None)), \
             patch.object(user_kb, 'get_setting', AsyncMock(side_effect=lambda key, default: default)), \
             patch('utils.miniapp.miniapp_url', return_value='https://example.com'):
            original = await user_kb.main_menu(42)
        support = next(b for row in original.inline_keyboard for b in row if b.callback_data == 'tk_user:0')
        self.assertEqual((support.text, support.icon_custom_emoji_id), ('Мои обращения', '1001'))
        decorated = icons.decorate(original)
        for row in original.inline_keyboard:
            for before in row:
                if before.icon_custom_emoji_id:
                    after = next(b for r in decorated.inline_keyboard for b in r
                                 if b.callback_data == before.callback_data and b.text == before.text)
                    self.assertEqual(after.model_dump(), before.model_dump())

    async def test_outgoing_send_and_edit_preserve_payload_and_do_not_mutate_original(self):
        icons.PACK_ICONS['support'] = '1001'
        markup = keyboard(InlineKeyboardButton(text='🛟 Мои обращения', callback_data='tk_user:0'))
        for method in (SendMessage(chat_id=42, text='Body', reply_markup=markup, disable_notification=True),
                       EditMessageReplyMarkup(chat_id=42, message_id=7, reply_markup=markup)):
            with self.subTest(method=type(method).__name__):
                request = AsyncMock(return_value='sent')
                bot = object()
                self.assertEqual(await icons.MissingButtonIcons()(request, bot, method), 'sent')
                request.assert_awaited_once()
                sent_bot, sent_method = request.call_args.args
                self.assertIs(sent_bot, bot)
                self.assertIsNot(sent_method, method)
                after = sent_method.reply_markup.inline_keyboard[0][0]
                self.assertEqual((after.text, after.callback_data, after.icon_custom_emoji_id),
                                 ('Мои обращения', 'tk_user:0', '1001'))
                self.assertEqual(sent_method.model_dump(exclude={'reply_markup'}),
                                 method.model_dump(exclude={'reply_markup'}))
        self.assertEqual(markup.inline_keyboard[0][0].text, '🛟 Мои обращения')
        self.assertIsNone(markup.inline_keyboard[0][0].icon_custom_emoji_id)

    async def test_buttons_that_already_have_icons_and_unrelated_controls_are_untouched(self):
        original = keyboard(
            InlineKeyboardButton(text='Custom support', callback_data='tk_user:0', icon_custom_emoji_id='999'),
            InlineKeyboardButton(text='🇺🇸 USA', callback_data='cat_detail:us'),
            InlineKeyboardButton(text='+15550001234', callback_data='buy_acc:4'),
            InlineKeyboardButton(text='2', callback_data='stock_page:2'),
            InlineKeyboardButton(text='→', callback_data='stock_page:2'),
            InlineKeyboardButton(text='Ранее', callback_data='quality_reviews:1'),
            InlineKeyboardButton(text='Изменить эмодзи', callback_data='btn_set_emoji:key'),
            InlineKeyboardButton(text='Партнёрская ссылка', url='https://example.com'),
            InlineKeyboardButton(text='🚀 USDT $ (xRocket Pay)', callback_data='deposit_xrocket'),
        )
        self.assertIs(icons.decorate(original), original)

    async def test_semantic_actions_get_appropriate_icons_without_duplicate_pictograms(self):
        examples = [
            ('Есть проблема', 'purchase_help:3', 'support', 'Есть проблема'),
            ('Обратиться по гарантии', 'quality_warranty:3', 'warranty', 'Обратиться по гарантии'),
            ('Получить код', 'get_code:3', 'code', 'Получить код'),
            ('Подтвердить возврат', 'adm_refund_confirm:3', 'confirm', 'Подтвердить возврат'),
            ('Подтвердить отправку', 'bc_send:nonce', 'confirm', 'Подтвердить отправку'),
            ('Остановить рассылку', 'bc_stop:nonce', 'cancel', 'Остановить рассылку'),
            ('🔔 Уведомить о поступлении', 'stock_menu', 'notifications', 'Уведомить о поступлении'),
            ('🔎 Поиск', 'adm_search', 'search', 'Поиск'),
            ('📋 Журнал действий', 'adm_audit', 'audit', 'Журнал действий'),
            ('🏠 Назад', 'admin_promos_menu', 'back', 'Назад'),
        ]
        for text, callback, role, label in examples:
            with self.subTest(callback=callback):
                after = icons.decorate(keyboard(InlineKeyboardButton(text=text, callback_data=callback)))
                button = after.inline_keyboard[0][0]
                self.assertEqual(button.icon_custom_emoji_id, icons.icon_for(role))
                self.assertEqual((button.text, button.callback_data), (label, callback))
        app = InlineKeyboardButton(text='🛍 Открыть Mini App', web_app=WebAppInfo(url='https://example.com'))
        after = icons.decorate(keyboard(app)).inline_keyboard[0][0]
        self.assertEqual(after.text, 'Открыть Mini App')
        self.assertEqual(after.web_app, app.web_app)

    async def test_methods_without_keyboards_are_forwarded_unchanged(self):
        method = SendMessage(chat_id=42, text='Body')
        request = AsyncMock()
        bot = object()
        await icons.MissingButtonIcons()(request, bot, method)
        self.assertIs(request.call_args.args[1], method)
