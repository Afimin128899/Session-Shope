"""Search and audit views available only to administrators."""
from utils.i18n import tr
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
from utils.section_banners import answer_screen

admin_tools_router = Router()


class AdminSearch(StatesGroup):
    user = State()
    order = State()


def search_menu():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('Пользователь: ID или @username'), callback_data='adm_find_user')], [InlineKeyboardButton(text=tr('Заказ: номер покупки'), callback_data='adm_find_order')], [InlineKeyboardButton(text=tr('В админ-панель'), callback_data='admin_home')]])


@admin_tools_router.callback_query(F.data == 'adm_search')
async def open_search(call, state):
    if not is_admin(call.from_user.id):
        await answer_safe(call, tr('Доступ запрещён.'), show_alert=True)
        return
    await state.clear()
    await edit_message_safe(call, tr('🔎 <b>Поиск</b>\n\nЧто найти?'), reply_markup=search_menu())
    await answer_safe(call)


@admin_tools_router.callback_query(F.data.in_({'adm_find_user', 'adm_find_order'}))
async def start_search(call, state):
    if not is_admin(call.from_user.id):
        await answer_safe(call, tr('Доступ запрещён.'), show_alert=True)
        return
    user_mode = call.data == 'adm_find_user'
    await state.clear()
    await state.set_state(AdminSearch.user if user_mode else AdminSearch.order)
    await edit_message_safe(call, tr('Введите ID пользователя или точный @username.') if user_mode else tr('Введите номер покупки, например 123 или #123.'), reply_markup=search_menu())
    await answer_safe(call)


def user_card(user, orders):
    username = '@' + escape(user['username']) if user.get('username') else tr('не указан')
    text = tr('👤 <b>Пользователь {0}</b>\nUsername: {1}\nБаланс: <b>{2} ₽</b> / <b>{3} USDT</b>\n\n<b>Последние покупки (до 5):</b>\n', f"{user['id']}", f'{username}', f"{user['balance']:.2f}", f"{user['balance_usdt']:.2f}")
    rows = []
    for order in orders:
        text += f"#{order['id']} — {escape(str(order['date']))}\n"
        rows.append([InlineKeyboardButton(text=tr('Заказ #{0}', f"{order['id']}"), callback_data=f"adm_order:{order['id']}")])
    if not orders:
        text += tr('Покупок нет.')
    rows.append([InlineKeyboardButton(text=tr('Новый поиск'), callback_data='adm_search')])
    rows.append([InlineKeyboardButton(text=tr('В админ-панель'), callback_data='admin_home')])
    return (text, InlineKeyboardMarkup(inline_keyboard=rows))


def order_card(order):
    username = '@' + escape(order['username']) if order.get('username') else tr('не указан')
    status = order_status(order)
    text = tr('🛍 <b>Заказ #{0}</b>\n\nПокупатель: <code>{1}</code> ({2})\nТовар: <code>{3}</code>\nКатегория: {4}\nДата: {5}\nВалюта покупки: {6}\nСтатус: <b>{7}</b>', f"{order['id']}", f"{order['user_id']}", f'{username}', f"{order['account_id']}", f"{escape(str(order.get('country') or tr('не найдена')))}", f"{escape(str(order['date']))}", f"{escape(str(order.get('currency') or tr('не указана')))}", f'{status}')
    if order.get('status') == 'refunded' and order.get('refund_reason'):
        text += tr('\nВозвращено: {0} {1}', f"{order.get('refunded_amount')}", f"{escape(str(order.get('currency') or ''))}")
        text += tr('\nПричина: {0}', f"{escape(order['refund_reason'])}")
    return text


def order_menu(order):
    keyboard = search_menu()
    if order.get('ticket_id'):
        keyboard.inline_keyboard.insert(0, [InlineKeyboardButton(text=tr('Открыть обращение'), callback_data=f"tk:{order['ticket_id']}:0")])
    if order.get('status') in {'issued', 'completed'} and order.get('paid_amount') is not None:
        keyboard.inline_keyboard.insert(0, [InlineKeyboardButton(text=tr('Вернуть на баланс'), callback_data=f"adm_refund:{order['id']}")])
    return keyboard


@admin_tools_router.message(AdminSearch.user)
async def search_user(message, state):
    if not is_admin(message.from_user.id):
        return
    query = (message.text or '').strip()
    if not query or len(query) > 64:
        await message.answer(tr('Введите ID или @username длиной до 64 символов.'))
        return
    user = await find_user(query)
    if not user:
        await message.answer(tr('Пользователь не найден. Попробуйте другой ID или @username.'), reply_markup=search_menu())
        return
    orders = await user_orders(user['id'])
    text, keyboard = user_card(user, orders)
    await state.clear()
    await answer_screen(message, text, section='users', reply_markup=keyboard)


@admin_tools_router.message(AdminSearch.order)
async def search_order(message, state):
    if not is_admin(message.from_user.id):
        return
    value = (message.text or '').strip().removeprefix('#')
    if not value.isascii() or not value.isdigit() or len(value) > 10:
        await message.answer(tr('Введите числовой номер покупки, например #123.'))
        return
    order = await find_order(int(value))
    if not order:
        await message.answer(tr('Заказ не найден. Проверьте номер покупки.'), reply_markup=search_menu())
        return
    await state.clear()
    await answer_screen(message, order_card(order), section='orders', reply_markup=order_menu(order))


@admin_tools_router.callback_query(F.data.startswith('adm_order:'))
async def open_order(call, state):
    if not is_admin(call.from_user.id):
        await answer_safe(call, tr('Доступ запрещён.'), show_alert=True)
        return
    value = call.data.split(':', 1)[1]
    if not value.isascii() or not value.isdigit() or len(value) > 10:
        await answer_safe(call, tr('Некорректный номер покупки.'), show_alert=True)
        return
    order = await find_order(int(value))
    if not order:
        await answer_safe(call, tr('Заказ не найден.'), show_alert=True)
        return
    await state.clear()
    await edit_message_safe(call, order_card(order), reply_markup=order_menu(order))
    await answer_safe(call)


ACTIONS = {
    'balance_add': 'Изменение баланса', 'balance_set': 'Установка баланса',
    'account_price': 'Цена товара', 'category_price': 'Цены категории',
    'account_delete': 'Удаление товара',
    'ticket_reply': 'Ответ в обращении', 'ticket_close': 'Закрытие обращения', 'order_refund': 'Возврат заказа',
}
TARGETS = {'user': 'Пользователь', 'account': 'Товар', 'category': 'Категория', 'ticket': 'Обращение', 'order': 'Заказ'}


def audit_line(entry):
    created = entry['created_at'].replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Europe/Moscow'))
    details = json.loads(entry['details'])
    title = ACTIONS.get(entry['action'], entry['action'])
    target = TARGETS.get(entry['target_type'], entry['target_type'])
    text = tr('<b>#{0} · {1}</b>\n{2} МСК · Админ <code>{3}</code>\n{4}: <code>{5}</code>\n', f"{entry['id']}", f'{escape(title)}', f'{created:%d.%m.%Y %H:%M:%S}', f"{entry['admin_id']}", f'{escape(target)}', f"{escape(entry['target_id'])}")
    if entry['action'] == 'order_refund':
        text += tr('Возвращено: {0} {1}', f"{escape(str(details['amount']))}", f"{escape(details['currency'])}")
    elif entry['action'] in {'balance_add', 'balance_set', 'account_price'}:
        text += f"{escape(str(details['before']))} → {escape(str(details['after']))} {escape(details.get('currency', '₽'))}"
    elif entry['action'] == 'category_price':
        text += tr('Новая цена: {0} ₽; изменено: {1}', f"{escape(str(details['after']))}", f"{details['updated']}")
    elif entry['action'] == 'account_delete':
        text += tr('Категория: {0}; цена: {1} ₽', f"{escape(str(details['category']))}", f"{escape(str(details['price']))}")
    return text


@admin_tools_router.callback_query(F.data == 'adm_audit')
@admin_tools_router.callback_query(F.data.startswith('adm_audit:'))
async def show_audit(call, state):
    if not is_admin(call.from_user.id):
        await answer_safe(call, tr('Доступ запрещён.'), show_alert=True)
        return
    try:
        value = call.data.split(':', 1)[1] if ':' in call.data else '0'
        if not value.isascii() or not value.isdigit() or len(value) > 19:
            raise ValueError
        before_id = int(value)
        if before_id > 9223372036854775807:
            raise ValueError
    except ValueError:
        await answer_safe(call, tr('Некорректная страница.'), show_alert=True)
        return
    entries = await audit_entries(before_id)
    await state.clear()
    text = tr('📋 <b>Журнал действий</b>\n\n') + ('\n\n'.join((audit_line(e) for e in entries[:5])) if entries else tr('Записей пока нет.'))
    rows = []
    if len(entries) > 5:
        rows.append([InlineKeyboardButton(text=tr('Ранее'), callback_data=f"adm_audit:{entries[4]['id']}")])
    if before_id:
        rows.append([InlineKeyboardButton(text=tr('К последним записям'), callback_data='adm_audit')])
    rows.append([InlineKeyboardButton(text=tr('В админ-панель'), callback_data='admin_home')])
    await edit_message_safe(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)
