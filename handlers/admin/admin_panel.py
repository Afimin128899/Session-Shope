import logging
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import ADMIN_IDS
from utils.version import BOT_VERSION
from database.admin_tools import change_balance, change_account_price, change_category_price, remove_account
from database.db import (
    create_user,
    delete_promo,
    get_account,
    get_accounts_by_country,
    get_all_promocodes,
    get_all_users,
    get_stats,
    get_user,
    get_user_by_username,
    get_users_with_balance,
    update_account_country,
    get_setting,
    set_setting,
)
from keyboards.admin_kb import (
    account_detail_menu,
    accounts_list_menu,
    back_to_admin,
    balance_menu,
    confirm_delete_acc_menu,
    get_admin_panel,
    prices_menu,
    promos_menu,
    get_settings_menu,
)
from services.telethon_code import try_fetch_login_code
from utils.nav import edit_message_safe, answer_safe

admin_router = Router()


def tg_emoji(emoji_id: str, fallback: str) -> str:
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


from utils.emoji_map import (
    EMOJI_LOCK, EMOJI_EXCLAMATION, EMOJI_CROSS, EMOJI_CHECK,
    EMOJI_USERS, EMOJI_USER_ALT, EMOJI_PACKAGE, EMOJI_BRIEFCASE,
    EMOJI_COIN, EMOJI_MEGA, EMOJI_TRASH, EMOJI_CLOCK,
    EMOJI_STAR, EMOJI_ART, EMOJI_CHART, EMOJI_HOME,
    EMOJI_ROBOT, EMOJI_PLUS, EMOJI_CYCLE, EMOJI_INFO, EMOJI_BACK,
    ADMIN_PANEL, ADMIN_SEARCH, ADMIN_CROWN, ADMIN_MAIL, ADMIN_BANK,
)

LOCK = tg_emoji(EMOJI_LOCK, "🔒")
PANEL = tg_emoji(ADMIN_PANEL, "🖥")
INFO = tg_emoji(EMOJI_INFO, "ℹ️")
ALERT = tg_emoji(EMOJI_EXCLAMATION, "❗️")
DENY = tg_emoji(EMOJI_CROSS, "❌")
OK = tg_emoji(EMOJI_CHECK, "✅")
USERS = tg_emoji(EMOJI_USERS, "👥")
USER = tg_emoji(EMOJI_USER_ALT, "👤")
ACCOUNT = tg_emoji(EMOJI_PACKAGE, "📦")
SEARCH = tg_emoji(ADMIN_SEARCH, "🔍")
BRIEFCASE = tg_emoji(EMOJI_BRIEFCASE, "💼")
BALANCE = tg_emoji(EMOJI_COIN, "🪙")
BROADCAST = tg_emoji(EMOJI_MEGA, "📢")
TRASH = tg_emoji(EMOJI_TRASH, "🗑")
CLOCK = tg_emoji(EMOJI_CLOCK, "🕓")
CROWN = tg_emoji(ADMIN_CROWN, "👑")
GIFT = tg_emoji(EMOJI_STAR, "⭐️")
ART = tg_emoji(EMOJI_ART, "🎨")
CHART = tg_emoji(EMOJI_CHART, "📊")
MAIL = tg_emoji(ADMIN_MAIL, "📨")
HOME = tg_emoji(EMOJI_HOME, "🏠")
ROBOT = tg_emoji(EMOJI_ROBOT, "🤖")
PLUS = tg_emoji(EMOJI_PLUS, "➕")
STAR = tg_emoji(EMOJI_STAR, "⭐️")
COIN = tg_emoji(EMOJI_COIN, "🪙")
BANK = tg_emoji(ADMIN_BANK, "🏦")
EXCHANGE = tg_emoji(EMOJI_CYCLE, "🔄")
UP = tg_emoji("5260379144167890225", "🔼")
DOWN = tg_emoji("5258336354642697821", "🔽")


class PriceState(StatesGroup):
    waiting_for_new_price = State()


class AdminBalanceState(StatesGroup):
    waiting_for_currency = State()
    waiting_for_user_id = State()
    waiting_for_amount = State()


class EditCountryState(StatesGroup):
    waiting_for_country = State()


class EditAccountPriceState(StatesGroup):
    waiting_for_price = State()


class AdminSettingsState(StatesGroup):
    waiting_for_support = State()
    waiting_for_reviews = State()
    waiting_for_tonkeeper = State()


def is_admin(user_id: int | str) -> bool:
    if not user_id:
        return False
    try:
        return int(user_id) in [int(x) for x in ADMIN_IDS]
    except (ValueError, TypeError):
        return False


@admin_router.message(Command("admin"))
@admin_router.message(F.text.in_(["/admin", "Админ-панель", "🎮 Админ-панель", "🖥 Админ-панель", "Админ панель"]))
async def admin_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer(
        f"{PANEL} <b>Премиум админ-панель</b>\n\n{CROWN} Добро пожаловать в центр управления.\n\n{ROBOT} Версия бота: <code>{BOT_VERSION}</code>",
        reply_markup=get_admin_panel(),
    )


@admin_router.callback_query(F.data.in_(["admin_home", "admin_panel_button"]))
async def admin_home(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await answer_safe(call, "❌ Доступ запрещён.", show_alert=True)
        return
    await state.clear()
    await edit_message_safe(
        call,
        f"{PANEL} <b>Премиум админ-панель</b>\n\n{CROWN} Управляйте магазином, балансами и аккаунтами.\n\n{ROBOT} Версия бота: <code>{BOT_VERSION}</code>",
        reply_markup=get_admin_panel(),
    )
    await answer_safe(call)


@admin_router.callback_query(F.data == "admin_stats")
async def show_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await answer_safe(call)
        return

    stats = await get_stats()

    users_total = stats.get("users", 0)
    total_balance = float(stats.get("total_balance") or 0.0)
    total_balance_usdt = float(stats.get("total_balance_usdt") or 0.0)
    acc_available = stats.get("accounts_available", 0)
    acc_sold = stats.get("accounts_sold", 0)
    stock_value = float(stats.get("accounts_value") or 0.0)
    revenue = float(stats.get("revenue") or 0.0)
    purchases_count = stats.get("purchases", 0)
    profit = revenue - stock_value

    text = (
        f"{CHART} <b>Подробная статистика</b>\n\n"
        f"{USERS} <b>Пользователи</b>\n"
        f"Всего: <code>{users_total}</code>\n"
        f"Баланс всех пользователей: <tg-emoji emoji-id=\"5406976471153545018\">💎</tg-emoji> <code>{total_balance:.4f} TON</code> | <tg-emoji emoji-id=\"5406841020769936275\">💵</tg-emoji> <code>{total_balance_usdt:.2f} USDT</code>\n\n"
        f"{ACCOUNT} <b>Аккаунты</b>\n"
        f"В наличии: <code>{acc_available}</code>\n"
        f"Продано: <code>{acc_sold}</code>\n"
        f"Стоимость склада: <code>{stock_value:.2f}</code> {COIN}\n\n"
        f"{BANK} <b>Финансы</b>\n"
        f"Выручка: <code>{revenue:.2f}</code> {COIN}\n"
        f"Прибыль: <code>{profit:.2f}</code> {COIN}\n\n"
        f"{GIFT} <b>Промокоды</b>\n"
        f"Активных: <code>{stats.get('promos', 0)}</code>\n\n"
        f"{OK} <b>Успешных покупок:</b> <code>{purchases_count}</code>"
    )

    await edit_message_safe(call, text, reply_markup=get_admin_panel())
    await answer_safe(call)


@admin_router.callback_query(F.data == "admin_users")
async def show_users(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await answer_safe(call)
        return

    users_with_money = await get_users_with_balance()
    all_users = await get_all_users()
    all_users_count = len(all_users)

    if not users_with_money:
        text = (
            f"{USERS} <b>Пользователи</b>\n\n"
            f"Всего пользователей: <code>{all_users_count}</code>\n\n"
            f"{INFO} Пользователей с балансом больше нуля пока нет."
        )
    else:
        text = (
            f"{USERS} <b>Пользователи</b>\n\n"
            f"Всего пользователей: <code>{all_users_count}</code>\n"
            f"С деньгами на балансе: <code>{len(users_with_money)}</code>\n\n"
        )
        for u in users_with_money[:30]:
            balance = float(u.get("balance") or 0.0)
            balance_usdt = float(u.get("balance_usdt") or 0.0)
            text += (
                f"{USER} <code>{u['id']}</code> — "
                f"<tg-emoji emoji-id=\"5406976471153545018\">💎</tg-emoji> <code>{balance:.4f} TON</code> | "
                f"<tg-emoji emoji-id=\"5406841020769936275\">💵</tg-emoji> <code>{balance_usdt:.2f} USDT</code>\n"
            )

    await edit_message_safe(call, text, reply_markup=back_to_admin())
    await answer_safe(call)


@admin_router.callback_query(F.data == "admin_maintenance")
async def admin_maintenance_handler(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    from database.db import get_setting, set_setting
    enabled = (await get_setting("maintenance_mode", "0")).strip() == "1"
    new_value = "0" if enabled else "1"
    await set_setting("maintenance_mode", new_value)
    status = "ВКЛЮЧЕН" if new_value == "1" else "ВЫКЛЮЧЕН"
    await edit_message_safe(
        call,
        f"🔧 <b>Режим техработ</b>\n\n"
        f"Статус: <b>{status}</b>\n\n"
        f"{'Пользователи сейчас видят экран техработ.' if new_value == '1' else 'Пользователи снова могут пользоваться ботом.'}",
        reply_markup=get_admin_panel(),
    )
    await answer_safe(call, f"Режим техработ: {status}")


@admin_router.callback_query(F.data == "check_maintenance")
async def check_maintenance_from_admin(call: CallbackQuery):
    from database.db import get_setting
    enabled = (await get_setting("maintenance_mode", "0")).strip() == "1"
    await answer_safe(call, "🔧 Технические работы ещё идут." if enabled else "🟢 Бот доступен!", show_alert=True)


@admin_router.callback_query(F.data == "admin_balance_menu")
async def admin_balance_menu_handler(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    await edit_message_safe(
        call,
        f"{BALANCE} <b>Управление балансами</b>\n\n{INFO} Выберите действие:",
        reply_markup=balance_menu(),
    )


@admin_router.callback_query(F.data.in_(["admin_add_balance", "admin_set_balance"]))
async def admin_balance_step_1(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return

    mode = "add" if call.data == "admin_add_balance" else "set"
    await state.update_data(balance_mode=mode, balance_currency="RUB")
    await state.set_state(AdminBalanceState.waiting_for_user_id)

    msg = (
        f"{PLUS} <b>Введите ID или Username (@username)</b> пользователя для пополнения баланса (RUB ₽):"
        if mode == "add"
        else f"{STAR} <b>Введите ID или Username (@username)</b> пользователя для установки баланса (RUB ₽):"
    )
    await edit_message_safe(call, msg, reply_markup=back_to_admin())
    await answer_safe(call)


@admin_router.message(AdminBalanceState.waiting_for_user_id)
async def admin_balance_step_2(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    input_text = message.text.strip()
    target_user_id = None
    target_username = None

    if input_text.isdigit():
        target_user_id = int(input_text)
        user = await get_user(target_user_id)
        if user and user.get("username"):
            target_username = user["username"]
    else:
        clean_user = input_text.lstrip("@").strip().lower()
        # 1. Поиск по полю username в базе данных
        user = await get_user_by_username(clean_user)
        if user:
            target_user_id = user["id"]
            target_username = user.get("username") or clean_user
        else:
            # 2. Запрос через Telegram API
            try:
                chat = await message.bot.get_chat(f"@{clean_user}")
                if chat and chat.id:
                    target_user_id = chat.id
                    target_username = chat.username or clean_user
                    await create_user(target_user_id, target_username)
            except Exception as e:
                logging.warning(f"[admin] get_chat for @{clean_user} failed: {e}")

    if not target_user_id:
        await message.answer(
            f"{DENY} Пользователь <code>{input_text}</code> не найден по юзернейму.\n\n"
            f"💡 <b>Попробуйте ввести его числовой ID (например: <code>1407094701</code>):</b>"
        )
        return

    await state.update_data(target_user_id=target_user_id, target_username=target_username)
    await state.set_state(AdminBalanceState.waiting_for_amount)

    data = await state.get_data()
    currency = data.get("balance_currency", "RUB")
    curr_text = "USDT ($)" if currency == "USDT" else "RUB (₽)"
    user_label = f"@{target_username}" if target_username else f"ID: {target_user_id}"

    await message.answer(
        f"👤 Выбран пользователь: <b>{user_label}</b> (<code>{target_user_id}</code>)\n\n"
        f"{BALANCE} Теперь введите <b>сумму</b> в <b>{curr_text}</b> цифрами:"
    )


@admin_router.message(AdminBalanceState.waiting_for_amount)
async def admin_balance_step_3(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    try:
        amount = (message.text or "").replace(",", ".").strip()
        data = await state.get_data()
        uid = data["target_user_id"]
        target_username = data.get("target_username")
        mode = data["balance_mode"]
        currency = data.get("balance_currency", "RUB")

        user_label = f"@{target_username} (<code>{uid}</code>)" if target_username else f"<code>{uid}</code>"

        await change_balance(message.from_user.id, uid, amount, currency, mode)
        amount = float(amount)

        if currency == "USDT":
            if mode == "add":
                res_text = f"{OK} Пользователю {user_label} добавлено <b>{amount:.2f} USDT</b>"
            else:
                res_text = f"{OK} Пользователю {user_label} установлен баланс <b>{amount:.2f} USDT</b>"
        else:
            if mode == "add":
                res_text = f"{OK} Пользователю {user_label} добавлено <b>{amount:.2f} RUB</b>"
            else:
                res_text = f"{OK} Пользователю {user_label} установлен баланс <b>{amount:.2f} RUB</b>"

        await state.clear()
        await message.answer(res_text, reply_markup=get_admin_panel())

    except ValueError as exc:
        from html import escape
        await message.answer(f"{DENY} {escape(str(exc))}")


@admin_router.callback_query(F.data == "admin_prices_menu")
async def show_prices_menu(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return

    from database.db import get_all_categories
    cats = await get_all_categories()

    await edit_message_safe(
        call,
        f"{ART} <b>Управление ценами</b>\n\n{INFO} Выберите категорию:",
        reply_markup=prices_menu(cats),
    )
    await answer_safe(call)


@admin_router.callback_query(F.data.startswith("price_"))
async def start_change_price(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return

    from database.db import get_category
    slug = call.data.replace("price_", "")
    cat = await get_category(slug)

    await state.update_data(target_slug=slug)
    await state.set_state(PriceState.waiting_for_new_price)

    await edit_message_safe(
        call,
        f"{EXCHANGE} Категория: <b>{cat['name'] if cat else slug}</b>\n\n{ART} Введите новую цену в рублях (₽):",
        reply_markup=back_to_admin(),
    )
    await answer_safe(call)


@admin_router.message(PriceState.waiting_for_new_price)
async def process_new_price(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    import re
    text = message.text.strip()
    if not re.match(r'^\d+(\.\d{1,2})?$', text) or not 0 < float(text) <= 99_999_999.99:
        await message.answer(
            "❌ Цена должна быть от 0.01 до 99 999 999.99 ₽, не более 2 знаков после запятой.\n"
            "Пример: <code>1.50</code>"
        )
        return

    new_price = float(text)
    data = await state.get_data()
    slug = data.get("target_slug")

    updated = await change_category_price(message.from_user.id, slug, new_price)
    await state.clear()

    from database.db import get_category
    cat = await get_category(slug)
    cat_name = cat["name"] if cat else slug

    await message.answer(
        f"{OK} <b>Цена обновлена</b>\n\n"
        f"{EXCHANGE} Категория: <b>{cat_name}</b>\n"
        f"{COIN} Новая цена: <code>{new_price:.2f}</code> ₽\n"
        f"{INFO} Обновлено записей: <code>{updated}</code>",
        reply_markup=get_admin_panel(),
    )


@admin_router.callback_query(F.data == "admin_promos_menu")
async def show_promos_menu(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    await edit_message_safe(
        call,
        f"{GIFT} <b>Управление промокодами</b>\n\n{INFO} Выберите действие:",
        reply_markup=promos_menu(),
    )
    await answer_safe(call)


@admin_router.callback_query(F.data == "admin_list_promos")
async def list_promos(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return

    promos = await get_all_promocodes()
    if not promos:
        await edit_message_safe(call, f"{GIFT} Список промокодов пуст.", reply_markup=promos_menu())
        return

    kb_list = []
    text = f"{GIFT} <b>Действующие промокоды</b>\n\n"

    for p in promos:
        val = float(p["value"])
        text += (
            f"{GIFT} <code>{p['code']}</code> — <b>{val:.2f}</b> {'% скидки' if p.get('kind') == 'discount' else '₽ на баланс'} "
            f"(<code>{p['uses']}</code>/<code>{p['max_uses']}</code>)\n"
        )
        kb_list.append(
            [
                InlineKeyboardButton(
                    text=f"🗑 Удалить {p['code']}",
                    callback_data=f"admin_del_promo_confirm:{p['code']}",
                )
            ]
        )

    kb_list.append([InlineKeyboardButton(text="🏠 Назад", callback_data="admin_promos_menu")])
    await edit_message_safe(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list))
    await answer_safe(call)


@admin_router.callback_query(F.data.startswith("admin_del_promo_confirm:"))
async def process_delete_promo(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    promo_code = call.data.split(":")[1]
    await delete_promo(promo_code)
    await answer_safe(call, f"✅\xa0Удалено:\xa0{promo_code}", show_alert=True)
    await list_promos(call)


@admin_router.callback_query(F.data == "admin_accounts_list")
async def show_accounts_list_first_page(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    await show_accounts_page(call, 0)


@admin_router.callback_query(F.data.startswith("admin_accounts_page:"))
async def show_accounts_list_page(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    page = int(call.data.split(":")[1])
    await show_accounts_page(call, page)


async def show_accounts_page(call: CallbackQuery, page: int):
    accounts = await get_accounts_by_country("all")

    if not accounts:
        await edit_message_safe(
            call,
            f"{ACCOUNT} <b>База аккаунтов</b>\n\n{INFO} Список пока пуст.",
            reply_markup=back_to_admin(),
        )
        await answer_safe(call)
        return

    await edit_message_safe(
        call,
        f"{ACCOUNT} <b>База аккаунтов</b>\n\n"
        f"{SEARCH} Всего записей: <code>{len(accounts)}</code>\n"
        f"{INFO} Выберите аккаунт для управления.",
        reply_markup=accounts_list_menu(accounts, page),
    )
    await answer_safe(call)


@admin_router.callback_query(F.data.startswith("admin_account_detail:"))
async def show_account_detail(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return

    acc_id = int(call.data.split(":")[1])
    account = await get_account(acc_id)

    if not account:
        await answer_safe(call, "❌ Аккаунт не найден.", show_alert=True)
        return

    status_text = f"{OK} Свободен" if account["status"] == "available" else f"{DENY} Продан"

    from database.db import get_category
    cat_row = await get_category(account["country"])
    cat_display = f"{cat_row['name']}" if cat_row else account["country"]

    text = (
        f"{ACCOUNT} <b>Карточка аккаунта</b>\n\n"
        f"{INFO} Товар: <code>SBA-{account['id']:06d}</code>\n"
        f"Telegram ID: <code>{account.get('telegram_user_id') or 'Не сохранён'}</code>\n"
        f"{EXCHANGE} Категория: <b>{cat_display}</b>\n"
        f"{MAIL} Номер: <code>{account['number']}</code>\n"
        f"{LOCK} 2FA пароль: <code>{account.get('password') or '-'}</code>\n"
        f"{COIN} Цена: <code>{float(account['price']):.2f}</code> ₽\n"
        f"{CHART} Статус: {status_text}\n"
    )

    from database.spam_checks import description as spam_description
    text += "\nСпамблок: " + spam_description(account) + "\n"
    await edit_message_safe(call, text, reply_markup=account_detail_menu(acc_id))
    await answer_safe(call)


@admin_router.callback_query(F.data.startswith("admin_req_code:"))
async def direct_get_code_from_card(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        logging.warning(f"[admin_req_code] Non-admin user {call.from_user.id} tried to request code directly!")
        return

    acc_id = int(call.data.split(":")[1])
    logging.info(f"[admin_req_code] Admin {call.from_user.id} requested verification code for account ID: {acc_id}")
    
    account = await get_account(acc_id)

    if not account:
        logging.warning(f"[admin_req_code] Account ID {acc_id} not found.")
        await answer_safe(call, "❌ Аккаунт не найден.", show_alert=True)
        return

    session_str = account.get("data")
    phone_number = account.get("number") or "Unknown"
    logging.info(f"[admin_req_code] Found account record. Phone: {phone_number}. Session length: {len(session_str) if session_str else 0}")

    if not session_str or session_str == "✅ Сессия удалена (Покупка завершена)":
        logging.warning(f"[admin_req_code] Session for account ID {acc_id} is deleted or empty.")
        await answer_safe(call, "❌ Невозможно получить код. Сессия уже удалена.", show_alert=True)
        return

    await answer_safe(call, "⏳ Запрашиваем код...", show_alert=False)
    await edit_message_safe(call, f"{CLOCK} <i>Ожидаем код от Telegram для {phone_number}...</i>")

    logging.info(f"[admin_req_code] Initiating Telethon connection to fetch code for admin panel ({phone_number})...")
    code = await try_fetch_login_code(session_str, phone_number)

    if code == "SESSION_NOT_AUTHORIZED":
        logging.error(f"[admin_req_code] FAILED. Session for {phone_number} is no longer authorized (expired or logged out).")
        res_text = (
            f"{DENY} <b>Ошибка: Сессия не авторизована</b>\n\n"
            f"{MAIL} Номер: <code>{phone_number}</code>\n"
            f"{ALERT} Сессия аккаунта устарела, неактивна или была закрыта пользователем с другого устройства."
        )
    elif code:
        logging.info(f"[admin_req_code] SUCCESS! Code received for {phone_number}: {code}")
        res_text = (
            f"{OK} <b>Код успешно получен</b>\n\n"
            f"{MAIL} Номер: <code>{phone_number}</code>\n"
            f"{SEARCH} Код входа: <code>{code}</code>\n"
            f"{LOCK} 2FA пароль: <code>{account.get('password') or '-'}</code>"
        )
    else:
        logging.warning(f"[admin_req_code] FAILED. Code did not arrive for {phone_number} within wait limit.")
        res_text = (
            f"{ACCOUNT} <b>Информация об аккаунте</b>\n\n"
            f"{MAIL} Номер: <code>{phone_number}</code>\n"
            f"{ALERT} <b>Результат:</b> {CLOCK} Код пока не пришёл. Попробуйте ещё раз через пару секунд."
        )

    await edit_message_safe(call, res_text, reply_markup=account_detail_menu(acc_id))


@admin_router.callback_query(F.data.startswith("admin_del_acc_ask:"))
async def ask_delete_account(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return

    acc_id = int(call.data.split(":")[1])
    account = await get_account(acc_id)

    if not account:
        await answer_safe(call, "❌ Аккаунт не найден.", show_alert=True)
        return

    text = (
        f"{ALERT} <b>Подтвердите удаление аккаунта</b>\n\n"
        f"{INFO} Товар: <code>SBA-{account['id']:06d}</code>\n"
        f"Telegram ID: <code>{account.get('telegram_user_id') or 'Не сохранён'}</code>\n"
        f"{MAIL} Номер: <code>{account['number']}</code>\n\n"
        f"<i>{TRASH} Это действие необратимо. Если аккаунт был куплен, он пропадёт из истории покупок пользователя.</i>"
    )

    await edit_message_safe(call, text, reply_markup=confirm_delete_acc_menu(acc_id))
    await answer_safe(call)


@admin_router.callback_query(F.data.startswith("admin_del_acc_yes:"))
async def confirm_delete_account(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return

    acc_id = int(call.data.split(":")[1])
    account = await get_account(acc_id)

    if not account:
        await answer_safe(call, "❌ Аккаунт уже удалён или не найден.", show_alert=True)
        return

    try:
        removed = await remove_account(call.from_user.id, acc_id)
    except ValueError as exc:
        await answer_safe(call, str(exc), show_alert=True)
        return
    if not removed:
        await answer_safe(call, "Аккаунт уже удалён.", show_alert=True)
        return
    await answer_safe(call, "✅ Аккаунт успешно удалён.", show_alert=True)
    await show_accounts_page(call, 0)


@admin_router.callback_query(F.data.startswith("admin_edit_price:"))
async def edit_price_ask(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return

    acc_id = int(call.data.split(":")[1])
    account = await get_account(acc_id)

    if not account:
        await answer_safe(call, "❌ Аккаунт не найден.", show_alert=True)
        return

    await state.update_data(edit_price_acc_id=acc_id)
    await state.set_state(EditAccountPriceState.waiting_for_price)

    await edit_message_safe(
        call,
        f"{COIN} <b>Изменение цены</b>\n\n"
        f"Текущая цена: <b>{float(account['price']):.2f} ₽</b>\n\n"
        f"Введите новую цену в рублях (₽) (до 2 знаков после запятой):\n"
        f"Пример: <code>1.50</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="« Отмена", callback_data=f"admin_account_detail:{acc_id}")]
        ]),
    )
    await answer_safe(call)


@admin_router.message(EditAccountPriceState.waiting_for_price)
async def edit_price_save(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    import re
    text = message.text.strip()
    if not re.match(r'^\d+(\.\d{1,2})?$', text) or not 0 < float(text) <= 99_999_999.99:
        await message.answer(
            "❌ Цена должна быть от 0.01 до 99 999 999.99 ₽, не более 2 знаков после запятой.\n"
            "Пример: <code>1.50</code>"
        )
        return

    new_price = float(text)
    data = await state.get_data()
    acc_id = data.get("edit_price_acc_id")

    if not acc_id:
        await state.clear()
        await message.answer(f"{DENY} Ошибка: ID аккаунта не найден.", reply_markup=back_to_admin())
        return

    success = await change_account_price(message.from_user.id, acc_id, new_price)
    await state.clear()

    if success:
        await message.answer(
            f"{OK} <b>Цена изменена</b>\n\n"
            f"{ACCOUNT} ID: <code>{acc_id}</code>\n"
            f"{COIN} Новая цена: <b>{new_price:.2f} ₽</b>",
            reply_markup=back_to_admin(),
        )
    else:
        await message.answer(f"{DENY} Аккаунт не найден.", reply_markup=back_to_admin())


@admin_router.callback_query(F.data.startswith("admin_edit_country:"))
async def edit_country_ask(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return

    acc_id = int(call.data.split(":")[1])
    account = await get_account(acc_id)

    if not account:
        await answer_safe(call, "❌ Аккаунт не найден.", show_alert=True)
        return

    await state.update_data(edit_country_acc_id=acc_id)

    from database.db import get_all_categories, get_category
    cats = await get_all_categories()
    current_cat = await get_category(account["country"])
    current_name = current_cat["name"] if current_cat else account["country"]

    text = (
        f"{EXCHANGE} <b>Изменение категории</b>\n\n"
        f"Текущая: <b>{current_name}</b>\n\n"
        f"Выберите новую категорию:"
    )
    rows = []
    for c in cats:
        emoji = c.get("emoji")
        active = "✅" if c["is_active"] else "❌"
        if emoji and emoji.isdigit():
            rows.append([
                InlineKeyboardButton(
                    text=f"{c['name']} {active}",
                    callback_data=f"editcat_pick:{c['slug']}:{acc_id}",
                    icon_custom_emoji_id=emoji,
                )
            ])
        else:
            display_emoji = emoji or "📁"
            rows.append([
                InlineKeyboardButton(
                    text=f"{display_emoji} {c['name']} {active}",
                    callback_data=f"editcat_pick:{c['slug']}:{acc_id}",
                )
            ])
    rows.append([InlineKeyboardButton(text="« Отмена", callback_data=f"admin_account_detail:{acc_id}")])
    await edit_message_safe(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)


@admin_router.callback_query(F.data.startswith("editcat_pick:"))
async def edit_country_pick(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    parts = call.data.split(":")
    slug = parts[1]
    acc_id = int(parts[2])

    logging.info(f"[admin_panel] edit_country_pick: call.data={call.data}, slug={slug}, acc_id={acc_id}")

    success = await update_account_country(acc_id, slug)
    await state.clear()

    from database.db import get_category
    cat = await get_category(slug)
    cat_name = cat["name"] if cat else slug

    logging.info(f"[admin_panel] edit_country_pick: success={success}, cat_name={cat_name}")

    if success:
        await edit_message_safe(
            call,
            f"{OK} <b>Категория изменена</b>\n\n"
            f"{ACCOUNT} ID: <code>{acc_id}</code>\n"
            f"{EXCHANGE} Новая категория: <b>{cat_name}</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="« К аккаунту", callback_data=f"admin_account_detail:{acc_id}")],
            ]),
        )
    else:
        await edit_message_safe(
            call,
            f"{DENY} Аккаунт не найден.",
            reply_markup=back_to_admin(),
        )
    await answer_safe(call)


# ── Admin Settings Handlers ───────────────────────────────────────────

@admin_router.callback_query(F.data == "admin_settings_menu")
async def admin_settings_menu_handler(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await answer_safe(call)
        return
    await state.clear()
    
    support = await get_setting("support_username", "@ondas4k")
    reviews = await get_setting("reviews_link", "https://t.me")
    tonkeeper = await get_setting("tonkeeper_wallet", "Не задан")

    text = (
        f"<b>Системные Настройки</b>\n\n"
        f"<b>Поддержка:</b> <code>{support}</code>\n"
        f"<b>Отзывы:</b> <code>{reviews}</code>\n"
        f"<b>TON Кошелек:</b> <code>{tonkeeper}</code>\n\n"
        f"<i>Выберите параметр для редактирования:</i>"
    )
    await edit_message_safe(call, text, reply_markup=get_settings_menu())
    await answer_safe(call)


@admin_router.callback_query(F.data.startswith("admin_edit_setting:"))
async def admin_edit_setting_handler(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await answer_safe(call)
        return

    setting_key = call.data.split(":")[1]
    
    cancel_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="« Отмена", callback_data="admin_settings_menu")]]
    )

    if setting_key == "support_username":
        await state.set_state(AdminSettingsState.waiting_for_support)
        text = (
            "<b>Изменение контакта поддержки</b>\n\n"
            "Введите новый юзернейм поддержки (начинающийся с @) или внешнюю ссылку:\n"
            "Пример: <code>@ondas4k</code>"
        )
    elif setting_key == "reviews_link":
        await state.set_state(AdminSettingsState.waiting_for_reviews)
        text = (
            "<b>Изменение ссылки на отзывы</b>\n\n"
            "Введите новую ссылку на канал/группу отзывов:\n"
            "Пример: <code>https://t.me/reviews_channel</code>"
        )
    elif setting_key == "tonkeeper_wallet":
        await state.set_state(AdminSettingsState.waiting_for_tonkeeper)
        text = (
            "<b>Изменение TON-кошелька для оплаты</b>\n\n"
            "Введите новый TON-адрес:\n"
            "Пример: <code>UQ...</code> или <code>EQ...</code>"
        )
    else:
        await answer_safe(call, "Неверный параметр.", show_alert=True)
        return

    await edit_message_safe(call, text, reply_markup=cancel_kb)
    await answer_safe(call)


@admin_router.message(AdminSettingsState.waiting_for_support)
async def admin_save_support(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    val = message.text.strip()
    if not val:
        await message.answer("<b>Ошибка:</b> Значение не может быть пустым. Попробуйте еще раз:")
        return

    await set_setting("support_username", val)
    await state.clear()
    
    await message.answer(
        f"<b>Контакты поддержки обновлены!</b>\n\nНовое значение: <code>{val}</code>",
        reply_markup=get_admin_panel()
    )


@admin_router.message(AdminSettingsState.waiting_for_reviews)
async def admin_save_reviews(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    val = message.text.strip()
    if not val:
        await message.answer("<b>Ошибка:</b> Ссылка не может быть пустой. Попробуйте еще раз:")
        return

    if not val.startswith("http") and not val.startswith("t.me"):
        await message.answer("<b>Ошибка:</b> Ссылка должна начинаться с http://, https:// или t.me/. Попробуйте еще раз:")
        return

    await set_setting("reviews_link", val)
    await state.clear()
    
    await message.answer(
        f"<b>Ссылка на отзывы обновлена!</b>\n\nНовое значение: <code>{val}</code>",
        reply_markup=get_admin_panel()
    )


@admin_router.message(AdminSettingsState.waiting_for_tonkeeper)
async def admin_save_tonkeeper(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    val = message.text.strip()
    if not val:
        await message.answer("<b>Ошибка:</b> Адрес не может быть пустым. Попробуйте еще раз:")
        return

    # Простая валидация адреса TON (обычно 48 символов base64-url)
    if len(val) < 40 or len(val) > 60:
         await message.answer("<b>Ошибка:</b> Непохоже на валидный TON-адрес (обычно около 48 символов). Попробуйте еще раз:")
         return

    await set_setting("tonkeeper_wallet", val)
    await state.clear()
    
    await message.answer(
        f"<b>TON-кошелек для оплаты обновлен!</b>\n\nНовое значение: <code>{val}</code>",
        reply_markup=get_admin_panel()
    )


class AdminSubState(StatesGroup):
    waiting_for_channel = State()


@admin_router.callback_query(F.data == "admin_sub_menu")
async def admin_sub_menu_handler(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return

    from database.db import get_subscription_settings
    settings = await get_subscription_settings()

    is_enabled = settings["enabled"]
    channel_id = settings.get("channel_id", "")
    channel_url = settings.get("channel_url", "")

    status_str = "🟢 <b>ВКЛЮЧЕНА</b>" if is_enabled else "🔴 <b>ВЫКЛЮЧЕНА</b>"
    ch_str = f"<code>{channel_id}</code>" if channel_id else "<i>не привязан</i>"
    url_str = f"<b>{channel_url}</b>" if channel_url else "<i>не задана</i>"

    text = (
        f"<tg-emoji emoji-id='{EMOJI_MEGA}'>📢</tg-emoji> <b>Управление обязательной подпиской</b>\n\n"
        f"<blockquote>"
        f"Статус проверки: {status_str}\n"
        f"Канал: {ch_str}\n"
        f"Ссылка: {url_str}"
        f"</blockquote>\n\n"
        f"<i>Когда функция включена, обычные пользователи не смогут пользоваться ботом, пока не подпишутся на ваш канал.</i>"
    )

    toggle_btn_text = "🔴 Выключить подписку" if is_enabled else "🟢 Включить подписку"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="➕ Привязать / Изменить канал",
                callback_data="admin_sub_set",
                icon_custom_emoji_id=EMOJI_PLUS,
            )
        ],
        [
            InlineKeyboardButton(
                text=toggle_btn_text,
                callback_data="admin_sub_toggle",
            )
        ],
        [
            InlineKeyboardButton(
                text="🗑 Сбросить канал",
                callback_data="admin_sub_clear",
                icon_custom_emoji_id=EMOJI_TRASH,
            )
        ],
        [
            InlineKeyboardButton(
                text="« В админку",
                callback_data="admin_home",
                icon_custom_emoji_id="5258236805890710909",
            )
        ]
    ])

    await edit_message_safe(call, text, reply_markup=kb)
    await answer_safe(call)


@admin_router.callback_query(F.data == "admin_sub_toggle")
async def admin_sub_toggle_handler(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return

    from database.db import get_subscription_settings, set_setting
    settings = await get_subscription_settings()

    if not settings.get("channel_id"):
        await answer_safe(call, "❌ Сначала привяжите канал перед включением подписки!", show_alert=True)
        return

    new_val = "0" if settings["enabled"] else "1"
    await set_setting("sub_channel_enabled", new_val)

    state_text = "включена" if new_val == "1" else "выключена"
    await answer_safe(call, f"✅ Обязательная подписка {state_text}!", show_alert=True)
    await admin_sub_menu_handler(call)


@admin_router.callback_query(F.data == "admin_sub_clear")
async def admin_sub_clear_handler(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return

    from database.db import set_setting
    await set_setting("sub_channel_id", "")
    await set_setting("sub_channel_url", "")
    await set_setting("sub_channel_enabled", "0")

    await answer_safe(call, "🗑 Настройки канала полностью сброшены.", show_alert=True)
    await admin_sub_menu_handler(call)


@admin_router.callback_query(F.data == "admin_sub_set")
async def admin_sub_set_handler(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return

    await state.set_state(AdminSubState.waiting_for_channel)

    text = (
        f"<tg-emoji emoji-id='{EMOJI_MEGA}'>📢</tg-emoji> <b>Привязка канала обязательной подписки</b>\n\n"
        f"Отправьте юзернейм канала (например: <code>@mychannel</code>) или ссылку (например: <code>https://t.me/mychannel</code>):\n\n"
        f"<b>⚠️ Важно:</b> Не забудьте <b>добавить бота в администраторы канала</b>, иначе он не сможет проверять подписку участников!"
    )

    await edit_message_safe(call, text, reply_markup=back_to_admin())
    await answer_safe(call)


@admin_router.message(AdminSubState.waiting_for_channel)
async def admin_sub_process_channel(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    input_text = message.text.strip()
    channel_id = None
    channel_url = None

    if "t.me/" in input_text:
        parts = input_text.split("t.me/")
        ch_name = parts[1].strip().split("/")[0].lstrip("@")
        channel_id = f"@{ch_name}"
        channel_url = f"https://t.me/{ch_name}"
    else:
        ch_name = input_text.lstrip("@").strip()
        channel_id = f"@{ch_name}"
        channel_url = f"https://t.me/{ch_name}"

    try:
        chat = await message.bot.get_chat(channel_id)
        if chat:
            channel_id = f"@{chat.username}" if chat.username else str(chat.id)
    except Exception as e:
        logging.warning(f"[admin] Failed to get chat info for {channel_id}: {e}")

    from database.db import set_setting
    await set_setting("sub_channel_id", channel_id)
    await set_setting("sub_channel_url", channel_url)
    await set_setting("sub_channel_enabled", "1")

    await state.clear()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Вернуться в настройки подписки", callback_data="admin_sub_menu")]
    ])

    await message.answer(
        f"<tg-emoji emoji-id='{EMOJI_CHECK}'>✅</tg-emoji> <b>Канал успешно привязан!</b>\n\n"
        f"<blockquote>"
        f"Канал: <code>{channel_id}</code>\n"
        f"Ссылка: {channel_url}\n"
        f"Статус: 🟢 <b>ВКЛЮЧЕНА</b>"
        f"</blockquote>\n\n"
        f"<i>Убедитесь, что бот является администратором канала {channel_id}.</i>",
        reply_markup=kb,
    )


@admin_router.callback_query(F.data == "market_report")
async def market_report(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Access denied", show_alert=True)
        return
    from datetime import datetime, timedelta
    from services.market_notifications import report, MOSCOW
    await call.answer()
    await call.message.answer(await report(datetime.now(MOSCOW).date() - timedelta(days=1)), parse_mode="HTML")
