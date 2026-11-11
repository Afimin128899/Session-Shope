"""Fill missing Telegram button icons from the tgmacicons custom emoji pack."""
import asyncio
import logging
import unicodedata

from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.types import InlineKeyboardMarkup

from utils import emoji_map as e

PACK_NAME = 'tgmacicons'
FALLBACK = {
    'support': e.EMOJI_CHAT, 'warranty': e.EMOJI_LOCK, 'orders': e.EMOJI_PACKAGE,
    'code': e.EMOJI_ROBOT, 'confirm': e.EMOJI_CHECK, 'cancel': e.EMOJI_CROSS,
    'back': e.EMOJI_ARROW_LEFT, 'home': e.EMOJI_HOME, 'edit': e.EMOJI_EDIT,
    'settings': e.EMOJI_INFO, 'delete': e.EMOJI_TRASH, 'add': e.EMOJI_PLUS,
    'money': e.EMOJI_COIN, 'refresh': e.EMOJI_CYCLE, 'catalog': e.EMOJI_PACKAGE,
    'reviews': e.EMOJI_STAR, 'notifications': e.EMOJI_MEGA, 'file': e.EMOJI_PAGE,
    'audit': e.EMOJI_PAGE, 'stats': e.EMOJI_CHART, 'users': e.EMOJI_USERS,
    'search': e.ADMIN_SEARCH,
}
CANDIDATES = {
    'support': ['💬', '🗨', '🛟'], 'warranty': ['🔒', '🛡'], 'orders': ['📦', '🛍'],
    'code': ['🤖', '🔑'], 'confirm': ['✅', '✔'], 'cancel': ['❌', '✖'],
    'back': ['⬅', '◀'], 'home': ['🏠', '🏘'], 'edit': ['✍', '✏'],
    'settings': ['⚙', 'ℹ'], 'delete': ['🗑'], 'add': ['➕'],
    'money': ['🪙', '💳', '💰'], 'refresh': ['🔄', '🔃'], 'catalog': ['📦', '🛒'],
    'reviews': ['⭐', '🌟'], 'notifications': ['🔔', '📣'], 'file': ['📄', '📁'],
    'audit': ['📋', '📄'], 'stats': ['📊', '📈'], 'users': ['👥', '👤'],
    'search': ['🔎', '🔍'],
}
PACK_ICONS = {}
logger = logging.getLogger(__name__)


def normalized(value):
    return ''.join(c for c in (value or '')
                   if c not in ('\ufe0f', '\ufe0e') and unicodedata.category(c) != 'Cf')


async def load_pack(bot):
    try:
        sticker_set = await asyncio.wait_for(bot.get_sticker_set(name=PACK_NAME), timeout=8)
        found = {}
        for sticker in sticker_set.stickers:
            if sticker.custom_emoji_id and sticker.emoji:
                found.setdefault(normalized(sticker.emoji), sticker.custom_emoji_id)
        mapped = {}
        for role, choices in CANDIDATES.items():
            for emoji in choices:
                if normalized(emoji) in found:
                    mapped[role] = found[normalized(emoji)]
                    break
        if not mapped:
            raise ValueError('No suitable icons')
        PACK_ICONS.clear()
        PACK_ICONS.update(mapped)
        logger.info('Button emoji pack %s loaded: %s roles', PACK_NAME, len(mapped))
        return True
    except Exception:
        # No exception text: SDK/network errors can contain a token-bearing URL.
        logger.warning('Button emoji pack %s unavailable; keeping local icon defaults', PACK_NAME)
        return False


def icon_for(role):
    return PACK_ICONS.get(role) or FALLBACK.get(role)


def clean_label(text):
    # Strip a duplicate leading pictogram only when adding a custom icon.
    markers = ('🛟', '🔔', '🔕', '🔎', '🔍', '📋', '📊', '🎟', '💳', '🔄', '🗑',
               '➕', '✏️', '✏', '🎭', '🖼️', '🖼', '🛍', '🏠')
    for marker in markers:
        if text.startswith(marker + ' '):
            return text[len(marker):].lstrip()
    return text


def role_for(button):
    text = clean_label(button.text).strip()
    data = button.callback_data or ''
    if data.startswith(('shop_mode:', 'shop_notice:', 'language')) or data == 'shop_status':
        return 'settings'
    if data.startswith(('review:', 'review_list:')):
        return 'search'
    if data.startswith('review_apply:'):
        return 'confirm'
    # Numeric navigation and category/account selectors carry their own meaning.
    if text in {'←', '→', '‹', '›', '«', '»', 'Новее', 'Ранее'} or text.isdecimal():
        return None
    if text.startswith(('« Назад', '« Отмена', 'Назад', 'К заказу', '« К ', '« В ')):
        return 'cancel' if 'Отмена' in text else 'back'
    if text in {'Отмена', 'Отменить'}:
        return 'cancel'
    if data.startswith(('btn_edit:', 'btn_cat:', 'buy_acc:', 'addacc_cat:',
                        'editcat_pick:', 'cat_detail:', 'price_', 'buy_')):
        return None
    if data in {'wheel','wheel_claim'} or data.startswith('purchase_promo:'):
        return 'reviews'
    if data.startswith('demo:'):
        return 'settings'
    if data.startswith('tk_photo:'):
        return 'file'
    if data.startswith(('spam_check:', 'spam_show:')) or data == 'spam_all':
        return 'warranty'
    if data == 'spam_all_yes':
        return 'confirm'
    if data == 'support_end':
        return 'back'
    if data == 'support' or data.startswith(('support_reply:', 'tk_reply:', 'tk_user:', 'tk_admin:', 'tk:', 'purchase_help:')):
        return 'support'
    if data.startswith('tk_close:'):
        return 'confirm'
    if data.startswith(('quality_warranty:', 'quality_features:')):
        return 'warranty'
    if data.startswith(('quality_review:', 'quality_reviews:')):
        return 'reviews'
    if data.startswith(('adm_refund_confirm:', 'refund_approve:', 'expand_confirm:', 'complete_confirm:', 'bc_send:')):
        return 'confirm'
    if data.startswith('bc_stop:'):
        return 'cancel'
    if data.startswith('adm_refund:'):
        return 'money'
    if data.startswith(('adm_order:', 'open_purchase:')) or data == 'my_purchases':
        return 'orders'
    if data.startswith('get_code:'):
        return 'code'
    if data.startswith('complete_purchase:'):
        return 'confirm'
    if data.startswith(('stock_on:', 'stock_off:')) or data == 'stock_menu':
        return 'notifications'
    if data.startswith(('stock_page:', 'adm_audit:')):
        return None
    # Payment providers already have their own visible brand pictograms.
    if data in {'deposit_xrocket', 'deposit_crypto'}:
        return None
    if data.startswith('deposit_') or data == 'toggle_currency':
        return 'money'
    if data.startswith(('lave_check:', 'xrocket_check:', 'crypto_check:', 'platega_check:')):
        return 'refresh'
    if data.startswith(('btn_set_label:', 'cat_edit_name:', 'cat_edit_emoji:',
                        'btn_edit_welcome_photo')):
        return 'edit'
    # Keep explicit icon editing controls and administrator previews unchanged.
    if data.startswith(('btn_set_emoji:', 'btn_clear_emoji:')):
        return None
    if data.startswith(('cat_create', 'cat_add_acc:')) or data == 'quality_discount':
        return 'add'
    if data.startswith(('cat_delete:', 'admin_del_promo_confirm:')):
        return 'delete'
    if data.startswith('cat_toggle:') or data in {'admin_sub_toggle', 'check_maintenance'}:
        return 'refresh'
    if data in {'main_menu', 'back_main', 'admin_home', 'admin_panel_button'}:
        return 'home'
    if data == 'back_buy':
        return 'back'
    if data == 'buy':
        return 'catalog'
    if data == 'market_report':
        return 'stats'
    if data == 'adm_audit':
        return 'audit'
    if data in {'adm_search', 'adm_find_order'}:
        return 'search'
    if data == 'adm_find_user':
        return 'users'
    if data in {'expand_tools', 'admin_btn_editor', 'admin_settings_menu', 'admin_sub_menu'}:
        return 'settings'
    if button.web_app and text in {'Открыть Mini App', 'Открыть товар'}:
        return 'catalog'
    if button.url and text == 'Оплатить':
        return 'money'
    return None


def decorate(markup):
    if not isinstance(markup, InlineKeyboardMarkup):
        return markup
    changed = False
    rows = []
    for row in markup.inline_keyboard:
        result = []
        for button in row:
            if button.icon_custom_emoji_id:
                result.append(button)
                continue
            identity = icon_for(role_for(button))
            if identity:
                result.append(button.model_copy(update={
                    'icon_custom_emoji_id': identity, 'text': clean_label(button.text),
                }))
                changed = True
            else:
                result.append(button)
        rows.append(result)
    return markup.model_copy(update={'inline_keyboard': rows}) if changed else markup


class MissingButtonIcons(BaseRequestMiddleware):
    async def __call__(self, make_request, bot, method):
        markup = getattr(method, 'reply_markup', None)
        decorated = decorate(markup)
        if decorated is not markup:
            method = method.model_copy(update={'reply_markup': decorated})
        return await make_request(bot, method)
