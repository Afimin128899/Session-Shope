"""Search and audit views available only to administrators."""
import json
from datetime import timezone
from html import escape
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.admin_tools import find_user, user_orders, find_order, audit_entries
from handlers.admin.admin_panel import is_admin
from utils.nav import answer_safe, edit_message_safe
from utils.order_status import order_status

admin_tools_router = Router()


class AdminSearch(StatesGroup):
    user = State()
    order = State()


def search_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='Пользователь: ID или @username', callback_data='adm_find_user')],
        [InlineKeyboardButton(text='Заказ: номер покупки', callback_data='adm_find_order')],
        [InlineKeyboardButton(text='В админ-панель', callback_data='admin_home')],
    ])


@admin_tools_router.callback_query(F.data == 'adm_search')
async def open_search(call, state):
    if not is_admin(call.from_user.id):
        await answer_safe(call, 'Доступ запрещён.', show_alert=True)
        return
    await state.clear()
    await edit_message_safe(call, '🔎 <b>Поиск</b>\n\nЧто найти?', reply_markup=search_menu())
    await answer_safe(call)


@admin_tools_router.callback_query(F.data.in_({'adm_find_user', 'adm_find_order'}))
async def start_search(call, state):
    if not is_admin(call.from_user.id):
        await answer_safe(call, 'Доступ запрещён.', show_alert=True)
        return
    user_mode = call.data == 'adm_find_user'
    await state.clear()
    await state.set_state(AdminSearch.user if user_mode else AdminSearch.order)
    await edit_message_safe(
        call,
        'Введите ID пользователя или точный @username.' if user_mode else 'Введите номер покупки, например 123 или #123.',
        reply_markup=search_menu(),
    )
    await answer_safe(call)


def user_card(user, orders):
    username = '@' + escape(user['username']) if user.get('username') else 'не указан'
    text = (
        f"👤 <b>Пользователь {user['id']}</b>\n"
        f"Username: {username}\n"
        f"Баланс: <b>{user['balance']:.2f} ₽</b> / <b>{user['balance_usdt']:.2f} USDT</b>\n\n"
        '<b>Последние покупки (до 5):</b>\n'
    )
    rows = []
    for order in orders:
        text += f"#{order['id']} — {escape(str(order['date']))}\n"
        rows.append([InlineKeyboardButton(text=f"Заказ #{order['id']}", callback_data=f"adm_order:{order['id']}")])
    if not orders:
        text += 'Покупок нет.'
    rows.append([InlineKeyboardButton(text='Новый поиск', callback_data='adm_search')])
    rows.append([InlineKeyboardButton(text='В админ-панель', callback_data='admin_home')])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def order_card(order):
    username = '@' + escape(order['username']) if order.get('username') else 'не указан'
    status = order_status(order)
    return (
        f"🛍 <b>Заказ #{order['id']}</b>\n\n"
        f"Покупатель: <code>{order['user_id']}</code> ({username})\n"
        f"Товар: <code>{order['account_id']}</code>\n"
        f"Категория: {escape(str(order.get('country') or 'не найдена'))}\n"
        f"Дата: {escape(str(order['date']))}\n"
        f"Валюта покупки: {escape(str(order.get('currency') or 'не указана'))}\n"
        f"Статус: <b>{status}</b>"
    )


def order_menu(order):
    keyboard = search_menu()
    if order.get('ticket_id'):
        keyboard.inline_keyboard.insert(0, [InlineKeyboardButton(
            text='Открыть обращение', callback_data=f"tk:{order['ticket_id']}:0",
        )])
    return keyboard


@admin_tools_router.message(AdminSearch.user)
async def search_user(message, state):
    if not is_admin(message.from_user.id):
        return
    query = (message.text or '').strip()
    if not query or len(query) > 64:
        await message.answer('Введите ID или @username длиной до 64 символов.')
        return
    user = await find_user(query)
    if not user:
        await message.answer('Пользователь не найден. Попробуйте другой ID или @username.', reply_markup=search_menu())
        return
    orders = await user_orders(user['id'])
    text, keyboard = user_card(user, orders)
    await state.clear()
    await message.answer(text, reply_markup=keyboard)


@admin_tools_router.message(AdminSearch.order)
async def search_order(message, state):
    if not is_admin(message.from_user.id):
        return
    value = (message.text or '').strip().removeprefix('#')
    if not value.isascii() or not value.isdigit() or len(value) > 10:
        await message.answer('Введите числовой номер покупки, например #123.')
        return
    order = await find_order(int(value))
    if not order:
        await message.answer('Заказ не найден. Проверьте номер покупки.', reply_markup=search_menu())
        return
    await state.clear()
    await message.answer(order_card(order), reply_markup=order_menu(order))


@admin_tools_router.callback_query(F.data.startswith('adm_order:'))
async def open_order(call, state):
    if not is_admin(call.from_user.id):
        await answer_safe(call, 'Доступ запрещён.', show_alert=True)
        return
    value = call.data.split(':', 1)[1]
    if not value.isascii() or not value.isdigit() or len(value) > 10:
        await answer_safe(call, 'Некорректный номер покупки.', show_alert=True)
        return
    order = await find_order(int(value))
    if not order:
        await answer_safe(call, 'Заказ не найден.', show_alert=True)
        return
    await state.clear()
    await edit_message_safe(call, order_card(order), reply_markup=order_menu(order))
    await answer_safe(call)


ACTIONS = {
    'balance_add': 'Изменение баланса', 'balance_set': 'Установка баланса',
    'account_price': 'Цена товара', 'category_price': 'Цены категории',
    'account_delete': 'Удаление товара',
    'ticket_reply': 'Ответ в обращении', 'ticket_close': 'Закрытие обращения',
}
TARGETS = {'user': 'Пользователь', 'account': 'Товар', 'category': 'Категория', 'ticket': 'Обращение'}


def audit_line(entry):
    created = entry['created_at'].replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Europe/Moscow'))
    details = json.loads(entry['details'])
    title = ACTIONS.get(entry['action'], entry['action'])
    target = TARGETS.get(entry['target_type'], entry['target_type'])
    text = (
        f"<b>#{entry['id']} · {escape(title)}</b>\n"
        f"{created:%d.%m.%Y %H:%M:%S} МСК · Админ <code>{entry['admin_id']}</code>\n"
        f"{escape(target)}: <code>{escape(entry['target_id'])}</code>\n"
    )
    if entry['action'] in {'balance_add', 'balance_set', 'account_price'}:
        text += f"{escape(str(details['before']))} → {escape(str(details['after']))} {escape(details.get('currency', '₽'))}"
    elif entry['action'] == 'category_price':
        text += f"Новая цена: {escape(str(details['after']))} ₽; изменено: {details['updated']}"
    elif entry['action'] == 'account_delete':
        text += f"Категория: {escape(str(details['category']))}; цена: {escape(str(details['price']))} ₽"
    return text


@admin_tools_router.callback_query(F.data == 'adm_audit')
@admin_tools_router.callback_query(F.data.startswith('adm_audit:'))
async def show_audit(call, state):
    if not is_admin(call.from_user.id):
        await answer_safe(call, 'Доступ запрещён.', show_alert=True)
        return
    try:
        value = call.data.split(':', 1)[1] if ':' in call.data else '0'
        if not value.isascii() or not value.isdigit() or len(value) > 19:
            raise ValueError
        before_id = int(value)
        if before_id > 9223372036854775807:
            raise ValueError
    except ValueError:
        await answer_safe(call, 'Некорректная страница.', show_alert=True)
        return
    entries = await audit_entries(before_id)
    await state.clear()
    text = '📋 <b>Журнал действий</b>\n\n' + ('\n\n'.join(audit_line(e) for e in entries[:5]) if entries else 'Записей пока нет.')
    rows = []
    if len(entries) > 5:
        rows.append([InlineKeyboardButton(text='Ранее', callback_data=f"adm_audit:{entries[4]['id']}")])
    if before_id:
        rows.append([InlineKeyboardButton(text='К последним записям', callback_data='adm_audit')])
    rows.append([InlineKeyboardButton(text='В админ-панель', callback_data='admin_home')])
    await edit_message_safe(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)
