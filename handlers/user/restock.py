"""Subscribe and unsubscribe without storing state in process memory."""
from utils.i18n import tr
from hashlib import sha256

from aiogram import F, Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.db import get_all_categories
from database.restock import subscribe, unsubscribe, subscriptions
from utils.nav import answer_safe, edit_message_safe

restock_router = Router()
PAGE_SIZE = 8


def category_key(slug: str) -> str:
    # Category slugs can exceed Telegram's 64-byte callback_data limit.
    return sha256(slug.encode()).hexdigest()[:20]


async def render_subscriptions(call, page: int=0):
    current = await subscriptions(call.from_user.id)
    categories = [cat for cat in await get_all_categories() if cat['is_active'] or cat['slug'] in current]
    page = max(0, min(page, (len(categories) - 1) // PAGE_SIZE))
    rows = []
    for cat in categories[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]:
        active = cat['slug'] in current
        action = 'off' if active else 'on'
        rows.append([InlineKeyboardButton(text=f"{(tr('🔕 Отменить') if active else tr('🔔 Подписаться'))}: {cat['name'][:40]}", callback_data=f"stock_{action}:{category_key(cat['slug'])}:{page}")])
    navigation = []
    if page:
        navigation.append(InlineKeyboardButton(text='←', callback_data=f'stock_page:{page - 1}'))
    if (page + 1) * PAGE_SIZE < len(categories):
        navigation.append(InlineKeyboardButton(text='→', callback_data=f'stock_page:{page + 1}'))
    if navigation:
        rows.append(navigation)
    rows.append([InlineKeyboardButton(text=tr('Назад в магазин'), callback_data='buy')])
    await edit_message_safe(call, tr('🔔 <b>Уведомления о поступлении</b>\n\nВыберите категорию — сообщим один раз, когда в неё добавят новый товар. Подписку можно отменить здесь же.') + (tr('\n\nПока нет доступных категорий.') if not categories else ''), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@restock_router.callback_query(F.data == 'stock_menu')
@restock_router.callback_query(F.data.startswith('stock_page:'))
async def show_subscriptions(call):
    try:
        page = int(call.data.split(':')[1]) if ':' in call.data else 0
    except ValueError:
        await answer_safe(call, tr('Некорректная страница.'), show_alert=True)
        return
    await render_subscriptions(call, page)
    await answer_safe(call)


@restock_router.callback_query(F.data.startswith('stock_on:') | F.data.startswith('stock_off:'))
async def change_subscription(call):
    try:
        action, key, page = call.data.split(':')
        page = int(page)
    except ValueError:
        await answer_safe(call, tr('Некорректная подписка.'), show_alert=True)
        return
    categories = await get_all_categories()
    cat = next((c for c in categories if category_key(c['slug']) == key), None)
    if cat is None or (action == 'stock_on' and (not cat['is_active'])):
        await answer_safe(call, tr('Категория больше недоступна.'), show_alert=True)
        return
    if action == 'stock_on':
        await subscribe(call.from_user.id, cat['slug'])
    else:
        await unsubscribe(call.from_user.id, cat['slug'])
    await render_subscriptions(call, page)
    await answer_safe(call, tr('Подписка оформлена.') if action == 'stock_on' else tr('Подписка отменена.'))
