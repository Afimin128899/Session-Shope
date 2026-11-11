"""Agreed menu hierarchy, accessible information and unchanged financial wording source."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from test_payments import db
from keyboards import user_kb
from handlers.user import profile, start, language, purchases
from utils import constants, store_rules
from utils.i18n import LANGUAGE
from utils.legal import VERIFICATION_WORD, PRIVACY_URL, AGREEMENT_URL


def buttons(markup):
    return [button for row in markup.inline_keyboard for button in row]


class ProfileNavigationTests(unittest.IsolatedAsyncioTestCase):
    async def test_profile_keeps_all_agreed_actions_and_renames_old_funding_label(self):
        async def labels(key):
            return {'label':'Баланс и пополнить'} if key=='btn_balance' else None
        with patch.object(user_kb,'get_button_label',AsyncMock(side_effect=labels)):
            markup=await user_kb.profile_menu()
        result={button.callback_data:button.text for button in buttons(markup)}
        self.assertEqual(result,{'my_purchases':'Мои покупки','topup_balance':'Пополнить баланс',
            'referral_info':'Реферальная система','wheel':'Бонусы','promo':'Ввести промокод',
            'profile_rules':'Правила','profile_settings':'Настройки','back_main':'В главное меню'})
        self.assertNotIn('Отзывы',' '.join(result.values()))

    async def test_settings_information_and_back_form_a_round_trip(self):
        call=NS(data='profile_settings',from_user=NS(id=42),answer=AsyncMock())
        state=NS(clear=AsyncMock())
        with patch.object(profile,'edit_message_safe',AsyncMock()) as show:
            await profile.user_settings(call,state)
        menu=show.call_args.kwargs['reply_markup']
        self.assertEqual([b.callback_data for b in buttons(menu)],['profile_info','language','my_profile'])
        call.data=buttons(menu)[0].callback_data
        with patch.object(start,'edit_message_safe',AsyncMock()) as show:
            await start.show_info(call,state)
        self.assertEqual(show.call_args.args[1],constants.info_text())
        self.assertEqual(buttons(show.call_args.kwargs['reply_markup'])[-1].callback_data,'profile_settings')
        urls={b.url for b in buttons(show.call_args.kwargs['reply_markup']) if b.url}
        self.assertTrue({PRIVACY_URL,AGREEMENT_URL}<=urls)

    async def test_public_information_keeps_its_legacy_return_path(self):
        call=NS(data='info_menu',answer=AsyncMock())
        with patch.object(start,'edit_message_safe',AsyncMock()) as show:
            await start.show_info(call)
        self.assertEqual(buttons(show.call_args.kwargs['reply_markup'])[-1].callback_data,'back_main')

    async def test_rules_have_a_working_profile_return_without_database_changes(self):
        call=NS(answer=AsyncMock());state=NS(clear=AsyncMock())
        with patch.object(profile,'edit_message_safe',AsyncMock()) as show,patch.object(db,'get_setting',AsyncMock()) as setting:
            await profile.user_rules(call,state)
            setting.assert_not_awaited()
        self.assertEqual(show.call_args.args[1],store_rules.rules_text())
        self.assertEqual(buttons(show.call_args.kwargs['reply_markup'])[-1].callback_data,'my_profile')

    async def test_language_menu_returns_to_settings(self):
        self.assertEqual(buttons(language.language_menu())[-1].callback_data,'profile_settings')

    async def test_purchase_details_do_not_reintroduce_review_buttons(self):
        from database import refunds
        call=NS(from_user=NS(id=42),answer=AsyncMock())
        with patch.object(purchases,'get_purchase_for_user',AsyncMock(return_value={'status':'refunded'})),patch.object(refunds,'get_refund',AsyncMock(return_value=None)),patch.object(purchases,'edit_message_safe',AsyncMock()) as show:
            await purchases.render_order(call,7)
        self.assertFalse(any((b.callback_data or '').startswith('quality_review') for b in buttons(show.call_args.kwargs['reply_markup'])))


class InformationTextTests(unittest.TestCase):
    def test_information_preserves_original_body_and_shortens_only_footer(self):
        token=LANGUAGE.set('ru')
        try:
            self.assertEqual(constants.info_text(),constants.INFO_TEXT + '\n\nКод: <code>' + VERIFICATION_WORD + '</code>')
            self.assertNotIn('СБП:',constants.info_text())
            self.assertNotIn('Цена товара и корзины',constants.info_text())
            self.assertNotIn('Оплата Stars:',constants.info_text())
        finally: LANGUAGE.reset(token)

    def test_english_information_keeps_word_and_documents_without_funding_footer(self):
        token=LANGUAGE.set('en')
        try:
            text=constants.info_text()
            self.assertIn('Code: <code>'+VERIFICATION_WORD+'</code>',text)
            self.assertIn(PRIVACY_URL,text);self.assertIn(AGREEMENT_URL,text)
            self.assertNotIn('SBP top-ups:',text);self.assertNotIn('Stars:',text)
        finally: LANGUAGE.reset(token)

    def test_expanded_rules_fit_a_message_and_retain_order_specific_warranty_terms(self):
        self.assertGreater(len(store_rules.RU),1000)
        self.assertLess(len(store_rules.RU),4096)
        self.assertIn('первые три дня',store_rules.RU.lower())
        self.assertIn('не меняют и не продлевают',store_rules.RU)
        self.assertNotIn('гарантия аннулируется',store_rules.RU.lower())
