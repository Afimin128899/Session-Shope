"""Public documents supplied by the store owner; no personal details are invented."""
from aiogram.types import InlineKeyboardButton
from utils.i18n import tr
from utils.button_icons import icon_for

PRIVACY_URL = 'https://telegra.ph/POLITIKA-KONFIDENCIALNOSTI-SBAND-ACCS-11-05-2'
AGREEMENT_URL = 'https://telegra.ph/POLZOVATELSKOE-SOGLASHENIE-SBAND-ACCS-11-05'
ABOUT_URL = 'https://sbandsub.space/about'
VERIFICATION_WORD = 'mekbuda'


def document_rows():
    return [[InlineKeyboardButton(text=tr('Политика конфиденциальности'), url=PRIVACY_URL, icon_custom_emoji_id=icon_for('info'))],
            [InlineKeyboardButton(text=tr('Пользовательское соглашение'), url=AGREEMENT_URL, icon_custom_emoji_id=icon_for('info'))],
            [InlineKeyboardButton(text=tr('Цены и поддержка'), url=ABOUT_URL, icon_custom_emoji_id=icon_for('support'))]]


def information_button():
    return InlineKeyboardButton(text=tr('Информация'), callback_data='info_menu', icon_custom_emoji_id=icon_for('info'))
