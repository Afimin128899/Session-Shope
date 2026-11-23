from utils.i18n import tr
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from utils.emoji_map import (
    EMOJI_HELPER, EMOJI_DELETE, EMOJI_ACCOUNTS, EMOJI_USERS,
    EMOJI_BALANCE, EMOJI_PROMOS, EMOJI_PRICES, EMOJI_STATS,
    EMOJI_BROADCAST, EMOJI_SETTINGS, EMOJI_HOME_ALT, EMOJI_BACK,
    EMOJI_ADD, EMOJI_SET, EMOJI_LIST, EMOJI_COUNTRY,
    EMOJI_NEXT, EMOJI_PREV, EMOJI_CODE, EMOJI_WARNING,
    EMOJI_CANCEL, EMOJI_CHANGE, EMOJI_COIN, EMOJI_MEGA,
)

ICON_HELPER = EMOJI_HELPER
ICON_DELETE = EMOJI_DELETE
ICON_ACCOUNTS = EMOJI_ACCOUNTS
ICON_USERS = EMOJI_USERS
ICON_BALANCE = EMOJI_BALANCE
ICON_PROMOS = EMOJI_PROMOS
ICON_PRICES = EMOJI_PRICES
ICON_STATS = EMOJI_STATS
ICON_BROADCAST = EMOJI_BROADCAST
ICON_SETTINGS = EMOJI_SETTINGS
ICON_HOME = EMOJI_HOME_ALT
ICON_BACK = EMOJI_BACK
ICON_ADD = EMOJI_ADD
ICON_SET = EMOJI_SET
ICON_LIST = EMOJI_LIST
ICON_COUNTRY = EMOJI_COUNTRY
ICON_NEXT = EMOJI_NEXT
ICON_PREV = EMOJI_PREV
ICON_CODE = EMOJI_CODE
ICON_WARNING = EMOJI_WARNING
ICON_CANCEL = EMOJI_CANCEL
ICON_CHANGE = EMOJI_CHANGE
ICON_COIN = EMOJI_COIN


# Keep callback identifiers stable: existing operation handlers remain unchanged.
ADMIN_CATEGORIES = {
    'inventory': ('Товары и аккаунты', ICON_ACCOUNTS, [
        ('Все аккаунты', 'admin_accounts_list', ICON_LIST),
        ('На проверке', 'review_list:0', ICON_WARNING),
        ('Добавить по номеру', 'add_account_telethon', ICON_ADD),
        ('Загрузить .session', 'add_account_session', ICON_ACCOUNTS),
        ('Новая сессия и очистка', 'session_tool:open', ICON_SETTINGS),
        ('Категории', 'admin_categories', ICON_COUNTRY),
        ('Цены', 'admin_prices_menu', ICON_PRICES),
        ('Проверить спамблок', 'spam_all', ICON_HELPER),
        ('Удалить аккаунт', 'admin_del_account', ICON_DELETE),
    ]),
    'finance': ('Заказы и финансы', ICON_COIN, [
        ('Поиск заказа', 'adm_search', ICON_LIST),
        ('Инструменты магазина', 'expand_tools', ICON_SETTINGS),
        ('Статистика', 'admin_stats', ICON_STATS),
        ('Отчёт за вчера', 'market_report', ICON_STATS),
        ('Баланс покупателя', 'admin_balance_menu', ICON_BALANCE),
    ]),
    'people': ('Пользователи и промо', ICON_USERS, [
        ('Пользователи', 'admin_users', ICON_USERS),
        ('Помощники', 'helper_manage', ICON_HELPER),
        ('Промокоды', 'admin_promos_menu', ICON_PROMOS),
        ('Создать скидку', 'quality_discount', ICON_ADD),
        ('Рассылка', 'admin_broadcast', ICON_BROADCAST),
        ('Заблокировать', 'p:main_ban', ICON_DELETE),
        ('Разблокировать', 'p:main_unban', ICON_USERS),
    ]),
    'system': ('Настройки и безопасность', ICON_SETTINGS, [
        ('Режимы магазина', 'shop_status', ICON_SETTINGS),
        ('Тестовый магазин', 'demo:open', ICON_CODE),
        ('Партнёрские боты', 'p:list', ICON_USERS),
        ('Оформление бота', 'pedit:menu:0', ICON_CHANGE),
        ('Редактор кнопок', 'admin_btn_editor', ICON_CHANGE),
        ('Обязательная подписка', 'admin_sub_menu', EMOJI_MEGA),
        ('Настройки', 'admin_settings_menu', ICON_SETTINGS),
        ('Журнал действий', 'adm_audit', ICON_LIST),
        ('Техработы', 'admin_maintenance', ICON_WARNING),
    ]),
}


def get_admin_panel(category=None) -> InlineKeyboardMarkup:
    if category is not None:
        if category not in ADMIN_CATEGORIES:
            raise ValueError('Неизвестный раздел администратора.')
        entries = ADMIN_CATEGORIES[category][2]
        buttons = [InlineKeyboardButton(
            text=tr(title), callback_data=callback, icon_custom_emoji_id=icon,
            style='danger' if callback in {'admin_del_account', 'p:main_ban'} else None,
        ) for title, callback, icon in entries]
        rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
        rows.append([InlineKeyboardButton(text=tr('Назад в админку'), callback_data='admin_home', icon_custom_emoji_id=ICON_BACK)])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    rows = [[InlineKeyboardButton(text=tr(title), callback_data='admin_category:'+key,
                                  icon_custom_emoji_id=icon)]
            for key, (title, icon, _) in ADMIN_CATEGORIES.items()]
    rows.append([InlineKeyboardButton(text=tr('Поиск'), callback_data='adm_search', icon_custom_emoji_id=ICON_LIST),
                 InlineKeyboardButton(text=tr('Журнал'), callback_data='adm_audit', icon_custom_emoji_id=ICON_LIST)])
    from utils.miniapp import admin_miniapp_url
    url = admin_miniapp_url()
    if url:
        from aiogram.types import WebAppInfo
        rows.append([InlineKeyboardButton(text=tr('Открыть Mini App'), web_app=WebAppInfo(url=url), icon_custom_emoji_id=ICON_SETTINGS, style='primary')])
    rows.append([InlineKeyboardButton(text=tr('В главное меню'), callback_data='main_menu', icon_custom_emoji_id=ICON_HOME)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_settings_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Партнёрские боты',callback_data='p:list')],[InlineKeyboardButton(text='Главное меню и оформление',callback_data='pedit:menu:0')],[InlineKeyboardButton(text=tr('Реферальные награды'), callback_data='admin_referral_settings', icon_custom_emoji_id=ICON_SETTINGS)], [InlineKeyboardButton(text=tr('СБП: заглушка оплаты'), callback_data='admin_sbp_settings', icon_custom_emoji_id=ICON_SETTINGS)], [InlineKeyboardButton(text=tr('Поддержка'), callback_data='admin_edit_setting:support_username', icon_custom_emoji_id=ICON_HELPER), InlineKeyboardButton(text=tr('Отзывы'), callback_data='admin_edit_setting:reviews_link', icon_custom_emoji_id=ICON_STATS)], [InlineKeyboardButton(text=tr('TON Кошелек'), callback_data='admin_edit_setting:tonkeeper_wallet', icon_custom_emoji_id=ICON_COIN)], [InlineKeyboardButton(text=tr('Назад'), callback_data='admin_home', icon_custom_emoji_id=ICON_BACK)]])


def admin_reply_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('В админ-панель'), callback_data='admin_home', icon_custom_emoji_id=ICON_HOME)]])


def back_to_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('В админ-панель'), callback_data='admin_home', icon_custom_emoji_id=ICON_HOME)]])


def balance_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('Пополнить баланс'), callback_data='admin_add_balance', icon_custom_emoji_id=ICON_ADD), InlineKeyboardButton(text=tr('Установить баланс'), callback_data='admin_set_balance', icon_custom_emoji_id=ICON_SET)], [InlineKeyboardButton(text=tr('Назад'), callback_data='admin_home', icon_custom_emoji_id=ICON_BACK)]])


def promos_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('Создать промокод'), callback_data='admin_create_promo', icon_custom_emoji_id=ICON_PROMOS), InlineKeyboardButton(text=tr('Список промокодов'), callback_data='admin_list_promos', icon_custom_emoji_id=ICON_LIST)], [InlineKeyboardButton(text=tr('Назад'), callback_data='admin_home', icon_custom_emoji_id=ICON_BACK)]])


def prices_menu(categories: list) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for c in categories:
        emoji = c.get('emoji')
        text = c['name']
        if emoji and (not emoji.isdigit()):
            text = f'{emoji} {text}'
        if emoji and emoji.isdigit():
            btn = InlineKeyboardButton(text=text, callback_data=f"price_{c['slug']}", icon_custom_emoji_id=emoji)
        else:
            btn = InlineKeyboardButton(text=text, callback_data=f"price_{c['slug']}")
        row.append(btn)
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text=tr('Назад'), callback_data='admin_home', icon_custom_emoji_id=ICON_BACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def accounts_list_menu(accounts: list, page: int=0) -> InlineKeyboardMarkup:
    per_page = 10
    total_pages = (len(accounts) + per_page - 1) // per_page if accounts else 1
    start = page * per_page
    end = min(start + per_page, len(accounts))
    rows = []
    for acc in accounts[start:end]:
        rows.append([InlineKeyboardButton(text=f"{acc['country']} | {acc['number'][:12]}... | ID:{acc['id']}", callback_data=f"admin_account_detail:{acc['id']}", icon_custom_emoji_id=ICON_ACCOUNTS)])
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text=tr('Назад'), callback_data=f'admin_accounts_page:{page - 1}', icon_custom_emoji_id=ICON_PREV))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text=tr('Далее'), callback_data=f'admin_accounts_page:{page + 1}', icon_custom_emoji_id=ICON_NEXT))
    if nav_buttons:
        rows.append(nav_buttons)
    rows.append([InlineKeyboardButton(text=tr('Назад'), callback_data='admin_home', icon_custom_emoji_id=ICON_BACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def account_detail_menu(account_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('Проверить спамблок'), callback_data=f'spam_check:{account_id}')], [InlineKeyboardButton(text=tr('Характеристики и гарантия'), callback_data=f'quality_features:{account_id}')], [InlineKeyboardButton(text=tr('Удалить аккаунт'), callback_data=f'admin_del_acc_ask:{account_id}', icon_custom_emoji_id=ICON_DELETE)], [InlineKeyboardButton(text=tr('Изменить категорию'), callback_data=f'admin_edit_country:{account_id}', icon_custom_emoji_id=ICON_CHANGE), InlineKeyboardButton(text=tr('Изменить цену'), callback_data=f'admin_edit_price:{account_id}', icon_custom_emoji_id=ICON_COIN)], [InlineKeyboardButton(text=tr('К списку аккаунтов'), callback_data='admin_accounts_list', icon_custom_emoji_id=ICON_ACCOUNTS)]])


def confirm_delete_acc_menu(account_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('Да, удалить'), callback_data=f'admin_del_acc_yes:{account_id}', icon_custom_emoji_id=ICON_WARNING), InlineKeyboardButton(text=tr('Отмена'), callback_data=f'admin_account_detail:{account_id}', icon_custom_emoji_id=ICON_CANCEL)]])

