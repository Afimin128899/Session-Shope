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


def get_admin_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛟 Обращения покупателей", callback_data="tk_admin:active:0")],
            [
                InlineKeyboardButton(text="🔎 Поиск", callback_data="adm_search"),
                InlineKeyboardButton(text="📋 Журнал действий", callback_data="adm_audit"),
            ],
            [
                InlineKeyboardButton(
                    text="📞 По номеру",
                    callback_data="add_account_telethon",
                    icon_custom_emoji_id=ICON_HELPER,
                ),
                InlineKeyboardButton(
                    text="📁 .session",
                    callback_data="add_account_session",
                    icon_custom_emoji_id=ICON_ACCOUNTS,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Удалить",
                    callback_data="admin_del_account",
                    icon_custom_emoji_id=ICON_DELETE,
                ),
                InlineKeyboardButton(
                    text="Аккаунты",
                    callback_data="admin_accounts_list",
                    icon_custom_emoji_id=ICON_ACCOUNTS,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Пользователи",
                    callback_data="admin_users",
                    icon_custom_emoji_id=ICON_USERS,
                ),
                InlineKeyboardButton(
                    text="Баланс",
                    callback_data="admin_balance_menu",
                    icon_custom_emoji_id=ICON_BALANCE,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Промокоды",
                    callback_data="admin_promos_menu",
                    icon_custom_emoji_id=ICON_PROMOS,
                ),
                InlineKeyboardButton(
                    text="Цены",
                    callback_data="admin_prices_menu",
                    icon_custom_emoji_id=ICON_PRICES,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Статистика",
                    callback_data="admin_stats",
                    icon_custom_emoji_id=ICON_STATS,
                ),
                InlineKeyboardButton(
                    text="Рассылка",
                    callback_data="admin_broadcast",
                    icon_custom_emoji_id=ICON_BROADCAST,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Категории",
                    callback_data="admin_categories",
                    icon_custom_emoji_id=ICON_COUNTRY,
                ),
                InlineKeyboardButton(
                    text="Редактор кнопок",
                    callback_data="admin_btn_editor",
                    icon_custom_emoji_id=ICON_SETTINGS,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Обязательная подписка",
                    callback_data="admin_sub_menu",
                    icon_custom_emoji_id=EMOJI_MEGA,
                ),
                InlineKeyboardButton(
                    text="Настройки",
                    callback_data="admin_settings_menu",
                    icon_custom_emoji_id=ICON_SETTINGS,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔧 Техработы",
                    callback_data="admin_maintenance",
                    icon_custom_emoji_id=ICON_WARNING,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Выйти из админки",
                    callback_data="main_menu",
                    icon_custom_emoji_id=ICON_HOME,
                ),
            ],
        ]
    )


def get_settings_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Поддержка",
                    callback_data="admin_edit_setting:support_username",
                    icon_custom_emoji_id=ICON_HELPER,
                ),
                InlineKeyboardButton(
                    text="Отзывы",
                    callback_data="admin_edit_setting:reviews_link",
                    icon_custom_emoji_id=ICON_STATS,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="TON Кошелек",
                    callback_data="admin_edit_setting:tonkeeper_wallet",
                    icon_custom_emoji_id=ICON_COIN,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data="admin_home",
                    icon_custom_emoji_id=ICON_BACK,
                ),
            ],
        ]
    )


def admin_reply_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="В админ-панель",
                    callback_data="admin_home",
                    icon_custom_emoji_id=ICON_HOME,
                )
            ],
        ]
    )


def back_to_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="В админ-панель",
                    callback_data="admin_home",
                    icon_custom_emoji_id=ICON_HOME,
                )
            ],
        ]
    )


def balance_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Пополнить баланс",
                    callback_data="admin_add_balance",
                    icon_custom_emoji_id=ICON_ADD,
                ),
                InlineKeyboardButton(
                    text="Установить баланс",
                    callback_data="admin_set_balance",
                    icon_custom_emoji_id=ICON_SET,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data="admin_home",
                    icon_custom_emoji_id=ICON_BACK,
                ),
            ],
        ]
    )


def promos_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Создать промокод",
                    callback_data="admin_create_promo",
                    icon_custom_emoji_id=ICON_PROMOS,
                ),
                InlineKeyboardButton(
                    text="Список промокодов",
                    callback_data="admin_list_promos",
                    icon_custom_emoji_id=ICON_LIST,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data="admin_home",
                    icon_custom_emoji_id=ICON_BACK,
                ),
            ],
        ]
    )


def prices_menu(categories: list) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for c in categories:
        emoji = c.get("emoji")
        text = c["name"]
        if emoji and not emoji.isdigit():
            text = f"{emoji} {text}"

        if emoji and emoji.isdigit():
            btn = InlineKeyboardButton(
                text=text,
                callback_data=f"price_{c['slug']}",
                icon_custom_emoji_id=emoji,
            )
        else:
            btn = InlineKeyboardButton(
                text=text,
                callback_data=f"price_{c['slug']}",
            )
        row.append(btn)
        if len(row) == 2:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    rows.append([
        InlineKeyboardButton(
            text="Назад",
            callback_data="admin_home",
            icon_custom_emoji_id=ICON_BACK,
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def accounts_list_menu(accounts: list, page: int = 0) -> InlineKeyboardMarkup:
    per_page = 10
    total_pages = (len(accounts) + per_page - 1) // per_page if accounts else 1
    start = page * per_page
    end = min(start + per_page, len(accounts))

    rows = []
    for acc in accounts[start:end]:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{acc['country']} | {acc['number'][:12]}... | ID:{acc['id']}",
                    callback_data=f"admin_account_detail:{acc['id']}",
                    icon_custom_emoji_id=ICON_ACCOUNTS,
                )
            ]
        )

    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(
                text="Назад",
                callback_data=f"admin_accounts_page:{page - 1}",
                icon_custom_emoji_id=ICON_PREV,
            )
        )
    if page < total_pages - 1:
        nav_buttons.append(
            InlineKeyboardButton(
                text="Далее",
                callback_data=f"admin_accounts_page:{page + 1}",
                icon_custom_emoji_id=ICON_NEXT,
            )
        )

    if nav_buttons:
        rows.append(nav_buttons)

    rows.append(
        [
            InlineKeyboardButton(
                text="Назад",
                callback_data="admin_home",
                icon_custom_emoji_id=ICON_BACK,
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def account_detail_menu(account_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Удалить аккаунт",
                    callback_data=f"admin_del_acc_ask:{account_id}",
                    icon_custom_emoji_id=ICON_DELETE,
                )
            ],
            [
                InlineKeyboardButton(
                    text="Изменить категорию",
                    callback_data=f"admin_edit_country:{account_id}",
                    icon_custom_emoji_id=ICON_CHANGE,
                ),
                InlineKeyboardButton(
                    text="Изменить цену",
                    callback_data=f"admin_edit_price:{account_id}",
                    icon_custom_emoji_id=ICON_COIN,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="К списку аккаунтов",
                    callback_data="admin_accounts_list",
                    icon_custom_emoji_id=ICON_ACCOUNTS,
                )
            ],
        ]
    )


def confirm_delete_acc_menu(account_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, удалить",
                    callback_data=f"admin_del_acc_yes:{account_id}",
                    icon_custom_emoji_id=ICON_WARNING,
                ),
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data=f"admin_account_detail:{account_id}",
                    icon_custom_emoji_id=ICON_CANCEL,
                ),
            ]
        ]
    )
