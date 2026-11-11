from utils.i18n import tr
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from config import ADMIN_IDS, SUPPORT_USERNAME, REVIEWS_LINK
from database.db import get_first_available_account_by_country, get_available_categories, get_button_label, get_setting
from utils import constants as c
from utils.button_icons import icon_for, pack_icon_for, pack_text
from utils.emoji_map import EMOJI_PACKAGE, EMOJI_STAR, EMOJI_INFO, EMOJI_USER, EMOJI_GAME, EMOJI_HAND


async def _btn_text(key: str, default_label: str, default_emoji: str) -> tuple[str, str | None]:
    row = await get_button_label(key)
    if row:
        label = row.get("label") or default_label
        emoji_id = row.get("emoji_id") or default_emoji
    else:
        label = default_label
        emoji_id = default_emoji
    return label, emoji_id


async def main_menu(user_id: int | None=None) -> InlineKeyboardMarkup:
    label_balance, emoji_balance = await _btn_text('btn_balance', tr('Пополнить баланс'), c.BTN_ICON_SHOP)
    label_buy, emoji_buy = await _btn_text('btn_buy', tr('Купить аккаунт'), c.BTN_ICON_BUY)
    label_support, _ = await _btn_text('btn_support', tr('Техподдержка'), c.BTN_ICON_SUPPORT)
    label_profile, _ = await _btn_text('btn_profile', tr('Мой профиль'), EMOJI_USER)
    if label_balance.casefold() == 'баланс и пополнить':
        label_balance = tr('Пополнить баланс')
    rows = [
        [InlineKeyboardButton(text=pack_text(label_buy), callback_data='buy', icon_custom_emoji_id=pack_icon_for('catalog'), style='primary')],
        [InlineKeyboardButton(text=pack_text(label_balance), callback_data='topup_balance', icon_custom_emoji_id=pack_icon_for('money'), style='success')],
        [InlineKeyboardButton(text=pack_text(label_profile), callback_data='my_profile', icon_custom_emoji_id=pack_icon_for('users')),
         InlineKeyboardButton(text=pack_text(label_support), callback_data='support', icon_custom_emoji_id=pack_icon_for('support'))],
        [InlineKeyboardButton(text=tr('Все категории'), callback_data='all_categories:0', icon_custom_emoji_id=pack_icon_for('catalog'))],
    ]
    from utils.miniapp import customer_miniapp_url
    app_url = customer_miniapp_url()
    if app_url:
        rows.insert(0, [InlineKeyboardButton(text=tr('🛍 Открыть Mini App'), web_app=WebAppInfo(url=app_url))])
    is_admin_user = False
    try:
        is_admin_user = int(user_id) in [int(x) for x in ADMIN_IDS]
    except Exception:
        is_admin_user = False
    if is_admin_user:
        label_admin, emoji_admin = await _btn_text('btn_admin_panel', tr('Админ-панель'), EMOJI_GAME)
        rows.append([InlineKeyboardButton(text=pack_text(label_admin), callback_data='admin_panel_button', icon_custom_emoji_id=pack_icon_for('settings'))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def profile_menu():
    specs = [
        ('btn_purchases', tr('Мои покупки'), 'my_purchases', 'orders'),
        ('btn_balance', tr('Пополнить баланс'), 'topup_balance', 'money'),
        ('btn_referral_system', tr('Реферальная система'), 'referral_info', 'users'),
        ('btn_bonuses', tr('Бонусы'), 'wheel', 'reviews'),
        ('btn_promo', tr('Ввести промокод'), 'promo', 'reviews'),
        ('btn_rules', tr('Правила'), 'profile_rules', 'file'),
        ('btn_user_settings', tr('Настройки'), 'profile_settings', 'settings'),
    ]
    buttons = []
    for key, label, callback, role in specs:
        text, _ = await _btn_text(key, label, pack_icon_for(role))
        if key == 'btn_balance' and text.casefold() == 'баланс и пополнить':
            text = tr('Пополнить баланс')
        buttons.append(InlineKeyboardButton(text=pack_text(text), callback_data=callback, icon_custom_emoji_id=pack_icon_for(role)))
    rows = [[buttons[0]], [buttons[1]], [buttons[2]], buttons[3:5], buttons[5:7]]
    rows.append([InlineKeyboardButton(text=tr('В главное меню'), callback_data='back_main', icon_custom_emoji_id=pack_icon_for('back'))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def user_settings_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr('Информация'), callback_data='profile_info', icon_custom_emoji_id=pack_icon_for('file'))],
        [InlineKeyboardButton(text=tr('Язык'), callback_data='language', icon_custom_emoji_id=pack_icon_for('settings'))],
        [InlineKeyboardButton(text=tr('Назад в профиль'), callback_data='my_profile', icon_custom_emoji_id=pack_icon_for('back'))],
    ])


async def shop_menu() -> tuple[InlineKeyboardMarkup, bool]:
    cats = await get_available_categories()
    if not cats:
        return (InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('🔔 Уведомить о поступлении'), callback_data='stock_menu')], [InlineKeyboardButton(text=tr('Назад'), callback_data='back_main')]]), False)
    rows = []
    label_back, emoji_back = await _btn_text('btn_back_shop', tr('Назад'), c.BTN_ICON_BACK_SMILE)
    for cat in cats:
        slug = cat['slug']
        display_name = cat.get('name') or slug
        price = float(cat['min_price']) if cat.get('min_price') else 0.0
        cat_emoji = cat.get('emoji')
        if cat_emoji and cat_emoji.isdigit():
            label, _ = await _btn_text(f'shop_{slug}', f'{display_name} — {price:.2f} ₽', c.FLAG_US)
            rows.append([InlineKeyboardButton(text=label, callback_data=f'buy_{slug}', icon_custom_emoji_id=cat_emoji)])
        else:
            default_text = f'{display_name} — {price:.2f} ₽'
            label, emoji = await _btn_text(f'shop_{slug}', default_text, c.FLAG_US)
            rows.append([InlineKeyboardButton(text=label, callback_data=f'buy_{slug}', icon_custom_emoji_id=emoji)])
    rows.append([InlineKeyboardButton(text=tr('🔔 Уведомить о поступлении'), callback_data='stock_menu')])
    rows.append([InlineKeyboardButton(text=label_back, callback_data='back_main', icon_custom_emoji_id=emoji_back)])
    return (InlineKeyboardMarkup(inline_keyboard=rows), True)


async def confirm_buy_menu(sku: str, price_usdt: float) -> InlineKeyboardMarkup:
    label_buy_usdt, emoji_buy_usdt = await _btn_text('btn_buy_confirm_usdt', tr('Купить за {0} ₽', f'{price_usdt:.2f}'), c.BTN_ICON_BUY)
    label_cancel, emoji_cancel = await _btn_text('btn_cancel', tr('Отмена'), c.BTN_ICON_CANCEL)
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label_buy_usdt, callback_data=f'confirm_buy:{sku}:USDT', icon_custom_emoji_id=emoji_buy_usdt)], [InlineKeyboardButton(text=label_cancel, callback_data='back_buy', icon_custom_emoji_id=emoji_cancel)]])


async def after_purchase_menu(purchase_id: int) -> InlineKeyboardMarkup:
    label_code, emoji_code = await _btn_text('btn_get_code', tr('Получить код'), c.BTN_ICON_BUY)
    label_back, emoji_back = await _btn_text('btn_back_shop', tr('Назад в меню'), c.BTN_ICON_BACK_SMILE)
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=pack_text(label_code), callback_data=f'get_code:{purchase_id}', icon_custom_emoji_id=pack_icon_for('code'))], [InlineKeyboardButton(text=tr('Есть проблема'), callback_data=f'purchase_help:{purchase_id}', icon_custom_emoji_id=pack_icon_for('support'))], [InlineKeyboardButton(text=pack_text(label_back), callback_data='back_main', icon_custom_emoji_id=pack_icon_for('back'))]])


def purchases_list_menu(purchase_rows: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for p in purchase_rows:
        display_name = p.get('country_name') or p.get('country') or tr('Товар')
        rows.append([InlineKeyboardButton(text=tr('Открыть: {0}', f'{display_name[:18]}'), callback_data=f"open_purchase:{p['id']}")])
    rows.append([InlineKeyboardButton(text=tr('Назад'), callback_data='back_main', icon_custom_emoji_id=c.BTN_ICON_BACK_SMILE)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def purchase_detail_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('Назад'), callback_data='my_purchases', icon_custom_emoji_id=c.BTN_ICON_BACK_SMILE)]])


def promo_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('Назад'), callback_data='promo_cancel', icon_custom_emoji_id=c.BTN_ICON_BACK_SMILE)]])


def back_to_balance() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('Назад'), callback_data='balance', icon_custom_emoji_id=c.BTN_ICON_BACK_SMILE)]])


def back_to_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('Назад'), callback_data='back_main', icon_custom_emoji_id=c.BTN_ICON_BACK_SMILE)]])


def information_menu(back_callback='back_main') -> InlineKeyboardMarkup:
    from utils.legal import document_rows
    rows = document_rows()
    if back_callback == 'profile_settings':
        for row, role in zip(rows, ['file', 'file', 'support']):
            row[0] = row[0].model_copy(update={'icon_custom_emoji_id': pack_icon_for(role)})
        rows.append([InlineKeyboardButton(text=tr('Назад в настройки'), callback_data='profile_settings', icon_custom_emoji_id=pack_icon_for('back'))])
    else:
        rows += back_to_main_menu().inline_keyboard
    return InlineKeyboardMarkup(inline_keyboard=rows)


def balance_menu() -> InlineKeyboardMarkup:
    """Базовое меню баланса (без переключателя валюты — используется после зачисления).
    Для полного меню с переключателем используется edit_balance() в nav.py."""
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('Пополнить баланс'), callback_data='topup_balance', icon_custom_emoji_id=c.BTN_ICON_WALLET)], [InlineKeyboardButton(text=tr('Только ₽'), callback_data='toggle_currency')], [InlineKeyboardButton(text=tr('Назад'), callback_data='main_menu', icon_custom_emoji_id=c.BTN_ICON_BACK_SMILE)]])


def back_to_profile():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('Мой профиль'), callback_data='my_profile', icon_custom_emoji_id=icon_for('back'))]])
