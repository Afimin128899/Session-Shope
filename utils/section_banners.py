"""Local, public artwork for Telegram navigation; no customer data in images."""
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from aiogram.types import FSInputFile

ROOT = Path(__file__).resolve().parent.parent
SECTIONS = (
    'home', 'catalog', 'profile', 'wallet', 'orders', 'support', 'bonus',
    'promo', 'referrals', 'info', 'reviews', 'stock', 'admin', 'inventory',
    'users', 'stats', 'settings', 'broadcast', 'audit', 'demo',
)

# Exact actions take precedence over prefixes, e.g. buy_acc versus buy_<category>.
EXACT = {
    'back_main': 'home', 'main_menu': 'home', 'check_sub_status': 'home',
    'buy': 'catalog', 'back_buy': 'catalog',
    'my_profile': 'profile', 'promo_cancel': 'profile',
    'balance': 'wallet', 'toggle_currency': 'wallet', 'topup_balance': 'wallet',
    'my_purchases': 'orders', 'promo': 'promo', 'referral_info': 'referrals',
    'wheel': 'bonus', 'wheel_claim': 'bonus', 'info_menu': 'info',
    'stock_menu': 'stock', 'admin_home': 'admin', 'admin_panel_button': 'admin',
    'demo:exit': 'admin', 'expand_tools': 'settings',
    'admin_stats': 'stats', 'market_report': 'stats',
    'admin_users': 'users', 'adm_search': 'users', 'adm_find_user': 'users',
    'adm_find_order': 'orders', 'admin_broadcast': 'broadcast',
    'admin_balance_menu': 'wallet', 'admin_add_balance': 'wallet', 'admin_set_balance': 'wallet',
    'admin_prices_menu': 'inventory', 'admin_categories': 'inventory',
    'admin_accounts_list': 'inventory', 'admin_del_account': 'inventory',
    'admin_add_account': 'inventory', 'add_account_session': 'inventory',
    'add_account_telethon': 'inventory', 'cat_create': 'inventory',
    'admin_promos_menu': 'promo', 'admin_list_promos': 'promo',
    'admin_create_promo': 'promo', 'quality_discount': 'promo',
    'admin_settings_menu': 'settings', 'admin_btn_editor': 'settings',
    'admin_maintenance': 'settings', 'check_maintenance': 'home',
    'adm_audit': 'audit', 'spam_all': 'audit', 'spam_all_yes': 'audit',
}
PREFIXES = (
    ('demo:', 'demo'), ('tk_', 'support'), ('tk:', 'support'),
    ('purchase_help:', 'support'), ('quality_warranty:', 'support'),
    ('quality_reviews:', 'reviews'), ('quality_review:', 'reviews'),
    ('stock_', 'stock'), ('deposit_', 'wallet'), ('stars_buy:', 'wallet'),
    ('lave_check:', 'wallet'), ('xrocket_check:', 'wallet'), ('crypto_check:', 'wallet'),
    ('orders_page:', 'orders'), ('open_purchase:', 'orders'), ('get_code:', 'orders'),
    ('complete_purchase:', 'orders'), ('complete_confirm:', 'orders'), ('adm_order:', 'orders'),
    ('purchase_promo:', 'promo'), ('confirm_buy', 'orders'),
    ('shop_page:', 'catalog'), ('items_page:', 'catalog'), ('buy_', 'catalog'),
    ('spam_', 'audit'), ('adm_audit:', 'audit'), ('adm_refund', 'audit'),
    ('refund_approve:', 'audit'), ('expand_confirm:', 'settings'),
    ('quality_features:', 'inventory'), ('cat_', 'inventory'), ('addacc_', 'inventory'),
    ('admin_account', 'inventory'), ('admin_delete_account', 'inventory'),
    ('admin_del_acc_', 'inventory'), ('admin_req_code:', 'inventory'),
    ('admin_edit_price:', 'inventory'), ('admin_edit_country:', 'inventory'),
    ('editcat_pick:', 'inventory'), ('price_', 'inventory'),
    ('admin_del_promo', 'promo'), ('btn_', 'settings'),
    ('admin_sub_', 'settings'), ('admin_edit_setting:', 'settings'),
    ('bc_', 'broadcast'),
)


def section_for_callback(data):
    if not isinstance(data, str):
        return None
    if data in EXACT:
        return EXACT[data]
    return next((section for prefix, section in PREFIXES if data.startswith(prefix)), None)


class _VisibleHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def caption_fits(text, parse_mode='HTML'):
    """Telegram limits captions after entity parsing; count UTF-16 conservatively."""
    if str(parse_mode).upper() == 'HTML':
        parser = _VisibleHTML()
        parser.feed(text)
        text = ''.join(parser.parts)
    return len(text.encode('utf-16-le')) // 2 <= 1024


@dataclass(frozen=True)
class Banner:
    section: str
    path: Path
    stamp: tuple


@dataclass(frozen=True)
class CachedPhoto:
    stamp: tuple
    file_id: str
    unique_id: str


# One entry per bot/section; replacing an image invalidates its previous file ID.
_photos = {}


def banner_for(section):
    if section not in SECTIONS:
        return None
    path = ROOT / 'assets' / ('welcome.png' if section == 'home' else f'banners/{section}.png')
    try:
        stat = path.stat()
    except OSError:
        return None
    return Banner(section, path, (stat.st_mtime_ns, stat.st_size))


def _key(message, banner):
    bot_id = getattr(getattr(message, 'bot', None), 'id', 0)
    return (bot_id if isinstance(bot_id, int) else 0, banner.section)


def cached_photo(message, banner):
    cached = _photos.get(_key(message, banner))
    return cached if cached and cached.stamp == banner.stamp else None


def photo_input(message, banner):
    cached = cached_photo(message, banner)
    return cached.file_id if cached else FSInputFile(banner.path)


def remember_photo(message, banner, result):
    photos = getattr(result, 'photo', None)
    if isinstance(photos, (list, tuple)) and photos:
        photo = photos[-1]
        if isinstance(getattr(photo, 'file_id', None), str) and isinstance(getattr(photo, 'file_unique_id', None), str):
            _photos[_key(message, banner)] = CachedPhoto(banner.stamp, photo.file_id, photo.file_unique_id)


async def answer_screen(message, text, *, section, reply_markup=None, parse_mode='HTML'):
    """Explicit navigation entry points only: never decorate receipts or broadcasts."""
    banner = banner_for(section) if caption_fits(text, parse_mode) else None
    options = dict(reply_markup=reply_markup, parse_mode=parse_mode)
    if not banner:
        return await message.answer(text, **options)
    result = await message.answer_photo(photo_input(message, banner), caption=text, **options)
    remember_photo(message, banner, result)
    return result
