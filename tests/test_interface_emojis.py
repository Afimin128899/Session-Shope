"""Pack-only rendering without altering credentials, entity offsets or funding data."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from test_payments import db
from aiogram.client.default import DefaultBotProperties
from aiogram.methods import SendMessage, SendPhoto, EditMessageMedia, SendInvoice, AnswerCallbackQuery, CopyMessage
from aiogram.types import MessageEntity, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, CopyTextButton, LabeledPrice
from utils import button_icons as icons, interface_emojis as ui


class EmojiRenderingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        roles={'confirm':'101','tools':'102','settings':'103','warranty':'104','support':'105','reviews':'106','file':'107','refresh':'108','catalog':'109','rocket':'110'}
        glyphs={'✅':'101','🛠':'102','⚙':'103','🔒':'104','💬':'105','⭐':'106','📄':'107','🔄':'108','📦':'109','🚀':'110'}
        for target,values in [(icons.PACK_ICONS,roles),(icons.PACK_EMOJIS,glyphs)]:
            p=patch.dict(target,values,clear=True);p.start();self.addCleanup(p.stop)
        self.bot=NS(default=DefaultBotProperties(parse_mode='HTML'))

    def test_plain_clusters_are_complete_and_do_not_eat_normal_numbers(self):
        source='42 1.20 ₽ #123 * © ™ 👨‍👩‍👧‍👦 👍🏿 🇺🇸 1️⃣'
        plain=ui.strip_emojis(source)
        self.assertIn('42 1.20 ₽ #123 * © ™',plain)
        self.assertNotIn('\u200d',plain);self.assertNotIn('🏿',plain)
        self.assertFalse(any(flag for flag,_ in ui.segments(plain)))

    def test_html_replaces_ui_icons_but_preserves_credentials_and_urls(self):
        source='✅ <b>Покупка</b> <code>пароль⭐&amp;🔒</code> <pre>📦 сырой файл</pre> <a href="https://example.com/⭐?x=1&amp;y=2">Помощь 💬</a>'
        rendered=ui.render_html(source)
        self.assertIn('emoji-id="101"',rendered);self.assertIn('emoji-id="105"',rendered)
        self.assertIn('<code>пароль⭐&amp;🔒</code>',rendered)
        self.assertIn('<pre>📦 сырой файл</pre>',rendered)
        self.assertIn('href="https://example.com/⭐?x=1&amp;y=2"',rendered)
        self.assertEqual(ui.render_html(rendered),rendered)

    def test_old_custom_emoji_is_replaced_with_requested_pack(self):
        rendered=ui.render_html('<tg-emoji emoji-id="999">🔒</tg-emoji> Безопасность')
        self.assertNotIn('999',rendered);self.assertIn('emoji-id="104"',rendered)
        self.assertEqual(rendered.count('<tg-emoji'),1)

    def test_missing_pack_strips_ui_emoji_but_leaves_data_exact(self):
        with patch.dict(icons.PACK_ICONS,{},clear=True),patch.dict(icons.PACK_EMOJIS,{},clear=True):
            self.assertEqual(ui.render_html('✅ <b>Готово</b>').strip(),'<b>Готово</b>')
            self.assertEqual(ui.render_html('<code>пароль⭐</code>'),'<code>пароль⭐</code>')
            result=ui.format_method(SendMessage(chat_id=42,text='✅'),self.bot)
            self.assertEqual(result.text,'Готово')

    def test_unknown_decorations_do_not_remain_standard_emoji(self):
        rendered=ui.render_html('Декор 🦄 👨‍👩‍👧‍👦 🇺🇸 1️⃣')
        self.assertEqual(rendered.strip(),'Декор')

    def test_explicit_entities_are_rebuilt_without_broken_utf16_offsets(self):
        secret='⭐abc🔒'
        original=SendMessage(chat_id=42,text='✅ '+secret,parse_mode=None,
            entities=[MessageEntity(type='code',offset=2,length=len(secret.encode('utf-16-le'))//2)])
        result=ui.format_method(original,self.bot)
        self.assertEqual(result.parse_mode,'HTML');self.assertIsNone(result.entities)
        self.assertIn('<code>'+secret+'</code>',result.text)
        self.assertIn('emoji-id="101"',result.text)
        self.assertEqual(original.text,'✅ '+secret)

    def test_custom_emoji_entities_from_another_pack_are_remapped(self):
        original=SendMessage(chat_id=42,text='🚀 Оплата',parse_mode=None,
            entities=[MessageEntity(type='custom_emoji',offset=0,length=2,custom_emoji_id='999')])
        result=ui.format_method(original,self.bot)
        self.assertIsNone(result.entities);self.assertIn('emoji-id="110"',result.text)
        self.assertNotIn('999',result.text)

    def test_photo_and_edited_media_captions_keep_the_same_files(self):
        photo=SendPhoto(chat_id=42,photo='file-id',caption='📦 <b>Товар</b>')
        result=ui.format_method(photo,self.bot)
        self.assertEqual(result.photo,photo.photo);self.assertIn('emoji-id="109"',result.caption)
        media=EditMessageMedia(chat_id=42,message_id=7,media=InputMediaPhoto(media='same-file',caption='✅ Готово'))
        result=ui.format_method(media,self.bot)
        self.assertEqual(result.media.media,'same-file');self.assertEqual(result.message_id,7)
        self.assertIn('emoji-id="101"',result.media.caption)

    def test_inline_keyboard_remaps_foreign_icons_and_preserves_actions(self):
        original=InlineKeyboardButton(text='💬 Поддержка',callback_data='support',icon_custom_emoji_id='999',style='primary')
        copy=InlineKeyboardButton(text='📄 Скопировать',copy_text=CopyTextButton(text='код⭐/secret'))
        markup=InlineKeyboardMarkup(inline_keyboard=[[original,copy]])
        result=icons.decorate(markup)
        button=result.inline_keyboard[0][0]
        self.assertEqual((button.text,button.icon_custom_emoji_id,button.callback_data,button.style),('Поддержка','105','support','primary'))
        self.assertEqual(result.inline_keyboard[0][1].copy_text.text,'код⭐/secret')
        self.assertEqual(original.icon_custom_emoji_id,'999')

    def test_reply_keyboard_is_also_pack_only(self):
        markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='📦 Купить',request_contact=True)]],resize_keyboard=True)
        result=icons.decorate(markup)
        self.assertEqual(result.keyboard[0][0].text,'Купить')
        self.assertEqual(result.keyboard[0][0].icon_custom_emoji_id,'109')
        self.assertTrue(result.keyboard[0][0].request_contact);self.assertTrue(result.resize_keyboard)

    def test_invoice_keeps_payload_currency_prices_and_provider_parameters(self):
        original=SendInvoice(chat_id=42,title='⭐ Stars',description='💳 Пополнение',payload='owner:42:⭐',currency='XTR',
            prices=[LabeledPrice(label='Stars',amount=30)],provider_token='fixture')
        result=ui.format_method(original,self.bot)
        self.assertEqual(result.title,'Stars');self.assertEqual(result.description,'Пополнение')
        self.assertEqual(original.model_dump(exclude={'title','description'}),result.model_dump(exclude={'title','description'}))
        self.assertNotIn('<tg-emoji',result.title)

    def test_callback_alert_stays_plain_text(self):
        original=AnswerCallbackQuery(callback_query_id='q',text='✅ Готово',show_alert=True)
        result=ui.format_method(original,self.bot)
        self.assertEqual(result.text,'Готово');self.assertTrue(result.show_alert)
        self.assertEqual(result.callback_query_id,'q')

    def test_emoji_only_failure_is_not_reported_as_success(self):
        result=ui.format_method(AnswerCallbackQuery(callback_query_id='q',text='❌',show_alert=True),self.bot)
        self.assertEqual(result.text,'Внимание')
        with patch.dict(icons.PACK_ICONS,{},clear=True),patch.dict(icons.PACK_EMOJIS,{},clear=True):
            result=ui.format_method(SendMessage(chat_id=42,text='<b>❌</b>'),self.bot)
            self.assertEqual(result.text,'Внимание')

    def test_copied_user_messages_are_not_modified(self):
        original=CopyMessage(chat_id=42,from_chat_id=43,message_id=9,caption='Личное сообщение ⭐',parse_mode='HTML')
        self.assertIs(ui.format_method(original,self.bot),original)

    async def test_session_middleware_formats_both_text_and_keyboard(self):
        method=SendMessage(chat_id=42,text='✅ Успешно',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text='💬 Поддержка',callback_data='support')]]))
        request=AsyncMock(return_value='sent')
        self.assertEqual(await icons.MissingButtonIcons()(request,self.bot,method),'sent')
        sent=request.call_args.args[1]
        self.assertIn('emoji-id="101"',sent.text)
        self.assertEqual(sent.reply_markup.inline_keyboard[0][0].text,'Поддержка')
        self.assertEqual(method.text,'✅ Успешно')
