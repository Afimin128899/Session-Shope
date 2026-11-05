from utils.i18n import tr
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from config import ADMIN_IDS, SUPPORT_USERNAME, REVIEWS_LINK
from database.db import get_first_available_account_by_country, get_available_categories, get_button_label, get_setting
from utils import constants as c
from utils.button_icons import icon_for
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
    label_balance, emoji_balance = await _btn_text('btn_balance', tr('Баланс и пополнить'), c.BTN_ICON_SHOP)
    label_buy, emoji_buy = await _btn_text('btn_buy', tr('Купить Аккаунт'), c.BTN_ICON_BUY)
    label_purchases, emoji_purchases = await _btn_text('btn_purchases', tr('Мои покупки'), EMOJI_PACKAGE)
    label_support, emoji_support = await _btn_text('btn_support', tr('Поддержка'), c.BTN_ICON_SUPPORT)
    label_reviews, emoji_reviews = await _btn_text('btn_reviews', tr('Отзывы'), c.BTN_ICON_REVIEWS)
    label_promo, emoji_promo = await _btn_text('btn_promo', tr('Ввести промокод'), EMOJI_STAR)
    label_info, emoji_info = await _btn_text('btn_info', tr('Информация'), EMOJI_INFO)
    label_profile, emoji_profile = await _btn_text('btn_profile', tr('Мой профиль'), EMOJI_USER)
    support_val = await get_setting('support_username', SUPPORT_USERNAME)
    if support_val.startswith('http') or support_val.startswith('t.me'):
        support_url = support_val if support_val.startswith('http') else f'https://{support_val}'
    else:
        support_url = f"https://t.me/{support_val.lstrip('@')}"
    reviews_val = await get_setting('reviews_link', REVIEWS_LINK or 'https://t.me')
    if reviews_val.startswith('http') or reviews_val.startswith('t.me'):
        reviews_url = reviews_val if reviews_val.startswith('http') else f'https://{reviews_val}'
    else:
        reviews_url = f"https://t.me/{reviews_val.lstrip('@')}"
    rows = [[InlineKeyboardButton(text=label_buy, callback_data='buy', icon_custom_emoji_id=emoji_buy)], [InlineKeyboardButton(text=label_profile, callback_data='my_profile', icon_custom_emoji_id=emoji_profile)], [InlineKeyboardButton(text=label_info, callback_data='info_menu', icon_custom_emoji_id=emoji_info)]]
    from utils.miniapp import miniapp_url
    app_url = miniapp_url()
    if app_url:
        rows.insert(0, [InlineKeyboardButton(text=tr('🛍 Открыть Mini App'), web_app=WebAppInfo(url=app_url))])
    reviews_row = [InlineKeyboardButton(text=label_reviews, callback_data='quality_reviews:0', icon_custom_emoji_id=emoji_reviews)]
    if support_val:
        reviews_row.insert(0, InlineKeyboardButton(text=label_support, url=support_url, icon_custom_emoji_id=emoji_support))
    rows.append(reviews_row)
    is_admin_user = False
    try:
        is_admin_user = int(user_id) in [int(x) for x in ADMIN_IDS]
    except Exception:
        is_admin_user = False
    if is_admin_user:
        label_admin, emoji_admin = await _btn_text('btn_admin_panel', tr('Админ-панель'), EMOJI_GAME)
        rows.append([InlineKeyboardButton(text=label_admin, callback_data='admin_panel_button', icon_custom_emoji_id=emoji_admin)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def profile_menu():
    specs = [('btn_purchases', tr('Мои покупки'), 'my_purchases', 'orders'), ('btn_balance', tr('Баланс и пополнить'), 'balance', 'money'), ('btn_promo', tr('Ввести промокод'), 'promo', 'reviews'), ('btn_referral_system', tr('Реферальная система'), 'referral_info', 'users')]
    rows = []
    for key, label, callback, role in specs:
        text, emoji = await _btn_text(key, label, icon_for(role))
        rows.append([InlineKeyboardButton(text=text, callback_data=callback, icon_custom_emoji_id=emoji)])
    rows.insert(1, [InlineKeyboardButton(text=tr('Мои обращения'), callback_data='tk_user:0', icon_custom_emoji_id=icon_for('support'))])
    rows.append([InlineKeyboardButton(text=tr('Бонусы · Колесо удачи'), callback_data='wheel', icon_custom_emoji_id=icon_for('reviews'))])
    rows.append([InlineKeyboardButton(text=tr('🌐 Язык / Language'), callback_data='language')])
    rows.append([InlineKeyboardButton(text=tr('В главное меню'), callback_data='back_main', icon_custom_emoji_id=icon_for('back'))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label_code, callback_data=f'get_code:{purchase_id}', icon_custom_emoji_id=emoji_code)], [InlineKeyboardButton(text=tr('Есть проблема'), callback_data=f'purchase_help:{purchase_id}')], [InlineKeyboardButton(text=label_back, callback_data='back_main', icon_custom_emoji_id=emoji_back)]])


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


def balance_menu() -> InlineKeyboardMarkup:
    """Базовое меню баланса (без переключателя валюты — используется после зачисления).
    Для полного меню с переключателем используется edit_balance() в nav.py."""
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('Пополнить баланс'), callback_data='topup_balance', icon_custom_emoji_id=c.BTN_ICON_WALLET)], [InlineKeyboardButton(text=tr('Только ₽'), callback_data='toggle_currency')], [InlineKeyboardButton(text=tr('Назад'), callback_data='main_menu', icon_custom_emoji_id=c.BTN_ICON_BACK_SMILE)]])


def back_to_profile():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('Мой профиль'), callback_data='my_profile', icon_custom_emoji_id=icon_for('back'))]])
