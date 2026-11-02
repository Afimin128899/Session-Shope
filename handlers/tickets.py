"""Persistent conversations shared by customers and the support team."""
import logging
from datetime import timezone
from html import escape
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_IDS
from database.db import get_purchase_for_user
from database import tickets as store
from handlers.admin.admin_panel import is_admin
from utils.nav import edit_message_safe, answer_safe
from utils.order_status import TICKET_STATUSES

logger = logging.getLogger(__name__)
ticket_router = Router()
ticket_router.message.filter(F.chat.type == 'private')
ticket_router.callback_query.filter(F.message.chat.type == 'private')


class TicketInput(StatesGroup):
    new = State()
    reply = State()


def identifier(value):
    if not value.isascii() or not value.isdigit() or len(value) > 19:
        raise ValueError('Некорректный номер обращения.')
    number = int(value)
    if not 0 < number <= 9223372036854775807:
        raise ValueError('Некорректный номер обращения.')
    return number


def button(text, data):
    return [InlineKeyboardButton(text=text, callback_data=data)]


def order_back(order_id):
    return InlineKeyboardMarkup(inline_keyboard=[button('Назад к заказу', f'open_purchase:{order_id}')])


async def notify(bot, recipients, ticket_id, text):
    for recipient in set(recipients):
        try:
            await bot.send_message(
                recipient, f'{text}\nОбращение #{ticket_id}.',
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[button('Открыть обращение', f'tk:{ticket_id}:0')]),
            )
        except Exception:
            # Messages remain in the inbox even when Telegram cannot deliver an alert.
            logger.warning('Ticket alert delivery failed for recipient %s', recipient)


async def display_ticket(call, ticket_id, before_id=0):
    admin = is_admin(call.from_user.id)
    owner_id = None if admin else call.from_user.id
    ticket = await store.get_ticket(ticket_id, owner_id)
    if not ticket:
        await answer_safe(call, 'Обращение не найдено.', show_alert=True)
        return
    messages = await store.history(ticket_id, owner_id, before_id)
    text = (
        f"🛟 <b>Обращение #{ticket['id']} · заказ #{ticket['purchase_id']}</b>\n"
        f"Статус: <b>{TICKET_STATUSES.get(ticket['status'], 'Неизвестен')}</b>\n\n"
    )
    if ticket.get('warranty_claimed_at'):
        text += '🛡 Гарантийное обращение: принято в пределах срока.\n\n'
    if messages:
        item = messages[0]
        author = {'admin': 'Поддержка', 'user': 'Покупатель', 'system': 'Система'}[item['author_role']]
        created = item['created_at'].replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Europe/Moscow'))
        text += f'<b>{author} · {created:%d.%m.%Y %H:%M} МСК</b>\n{escape(item["body"])}'
    else:
        text += 'Сообщений на этой странице нет.'
    reply_label = 'Открыть снова и написать' if ticket['status'] == 'closed' else 'Ответить'
    rows = [button(reply_label, f'tk_reply:{ticket_id}')]
    if len(messages) > 1:
        rows.append(button('Предыдущее сообщение', f'tk:{ticket_id}:{messages[0]["id"]}'))
    rows.append(button('К последнему сообщению / Обновить', f'tk:{ticket_id}:0'))
    if admin:
        if ticket['status'] != 'closed':
            rows.append(button('Закрыть обращение', f'tk_close:{ticket_id}'))
        rows.append(button('К обращениям', 'tk_admin:active:0'))
    else:
        rows.append(button('Назад к заказу', f'open_purchase:{ticket["purchase_id"]}'))
        rows.append(button('Мои обращения', 'tk_user:0'))
    await edit_message_safe(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@ticket_router.callback_query(F.data.startswith('purchase_help:'))
async def purchase_help(call, state):
    try:
        order_id = identifier(call.data.split(':', 1)[1])
    except ValueError as exc:
        await answer_safe(call, str(exc), show_alert=True)
        return
    order = await get_purchase_for_user(order_id, call.from_user.id)
    if not order:
        await answer_safe(call, 'Покупка не найдена.', show_alert=True)
        return
    await state.clear()
    ticket = await store.ticket_for_order(order_id, call.from_user.id)
    if ticket:
        await display_ticket(call, ticket['id'])
    else:
        await state.update_data(ticket_order_id=order_id)
        await state.set_state(TicketInput.new)
        await edit_message_safe(
            call,
            f'🛟 <b>Помощь по заказу #{order_id}</b>\n\n'
            'Опишите проблему текстом (до 500 символов). Переписка сохранится в боте. '
            'Не отправляйте пароли, коды входа и данные сессий.',
            reply_markup=order_back(order_id),
        )
    await answer_safe(call)


@ticket_router.callback_query(F.data.startswith('tk:'))
async def open_ticket(call, state):
    try:
        _, value, before = call.data.split(':')
        ticket_id = identifier(value)
        before_id = identifier(before) if before != '0' else 0
    except ValueError:
        await answer_safe(call, 'Некорректный номер обращения.', show_alert=True)
        return
    await state.clear()
    await display_ticket(call, ticket_id, before_id)
    await answer_safe(call)


@ticket_router.callback_query(F.data.startswith('tk_reply:'))
async def start_reply(call, state):
    try:
        ticket_id = identifier(call.data.split(':', 1)[1])
    except ValueError as exc:
        await answer_safe(call, str(exc), show_alert=True)
        return
    admin = is_admin(call.from_user.id)
    ticket = await store.get_ticket(ticket_id, None if admin else call.from_user.id)
    if not ticket:
        await answer_safe(call, 'Обращение не найдено.', show_alert=True)
        return
    await state.clear()
    await state.update_data(ticket_id=ticket_id)
    await state.set_state(TicketInput.reply)
    await edit_message_safe(
        call,
        f'Введите ответ по обращению #{ticket_id} (до 500 символов).\n'
        'Если обращение закрыто, сообщение откроет его снова. Не отправляйте пароли и коды входа.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[button('Отмена', f'tk:{ticket_id}:0')]),
    )
    await answer_safe(call)


@ticket_router.message(TicketInput.new)
async def submit_ticket(message, state):
    try:
        data = await state.get_data()
        order_id = data.get('ticket_order_id')
        if order_id is None:
            raise ValueError('Выберите заказ в разделе «Мои покупки».')
        ticket_id = await store.create_ticket(message.from_user.id, order_id, message.text or '')
    except ValueError as exc:
        await message.answer(escape(str(exc)))
        return
    except Exception:
        logger.exception('Failed to save support message for user %s', message.from_user.id)
        await message.answer('Не удалось сохранить сообщение. Попробуйте отправить его ещё раз позже.')
        return
    await state.clear()
    await message.answer(
        f'✅ Обращение #{ticket_id} сохранено. Поддержка ответит здесь, в боте.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[button('Открыть обращение', f'tk:{ticket_id}:0')]),
    )
    await notify(message.bot, ADMIN_IDS, ticket_id, 'Новое сообщение покупателя.')


@ticket_router.message(TicketInput.reply)
async def submit_reply(message, state):
    admin = is_admin(message.from_user.id)
    try:
        data = await state.get_data()
        ticket_id = data.get('ticket_id')
        if ticket_id is None:
            raise ValueError('Откройте обращение заново.')
        user_id = await store.reply(ticket_id, message.from_user.id, message.text or '', admin=admin)
    except ValueError as exc:
        await message.answer(escape(str(exc)))
        return
    except Exception:
        logger.exception('Failed to save support message for user %s', message.from_user.id)
        await message.answer('Не удалось сохранить сообщение. Попробуйте отправить его ещё раз позже.')
        return
    await state.clear()
    await message.answer(
        '✅ Сообщение сохранено.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[button('К переписке', f'tk:{ticket_id}:0')]),
    )
    await notify(message.bot, [user_id] if admin else ADMIN_IDS, ticket_id,
                 'Поддержка ответила на ваше обращение.' if admin else 'Новое сообщение покупателя.')


@ticket_router.callback_query(F.data.startswith('tk_close:'))
async def close_ticket(call, state):
    if not is_admin(call.from_user.id):
        await answer_safe(call, 'Доступ запрещён.', show_alert=True)
        return
    try:
        ticket_id = identifier(call.data.split(':', 1)[1])
        user_id = await store.close_ticket(ticket_id, call.from_user.id)
    except ValueError as exc:
        await answer_safe(call, str(exc), show_alert=True)
        return
    await state.clear()
    await display_ticket(call, ticket_id)
    await answer_safe(call, 'Обращение закрыто.')
    if user_id is not None:
        await notify(call.bot, [user_id], ticket_id, 'Поддержка закрыла ваше обращение.')


@ticket_router.callback_query(F.data.startswith('tk_user:') | F.data.startswith('tk_admin:'))
async def show_inbox(call, state):
    try:
        parts = call.data.split(':')
        admin = parts[0] == 'tk_admin'
        if admin and not is_admin(call.from_user.id):
            await answer_safe(call, 'Доступ запрещён.', show_alert=True)
            return
        if admin:
            _, mode, value = parts
            if mode not in {'active', 'closed'}:
                raise ValueError
        else:
            _, value = parts
            mode = 'all'
        if not value.isascii() or not value.isdigit() or len(value) > 5:
            raise ValueError
        page = int(value)
        if page > 10000:
            raise ValueError
    except ValueError:
        await answer_safe(call, 'Некорректная страница.', show_alert=True)
        return
    entries = await store.inbox(None if admin else call.from_user.id, mode == 'closed', page)
    await state.clear()
    rows = [button(f"#{t['id']} · заказ #{t['purchase_id']} · {TICKET_STATUSES.get(t['status'], '')}",
                   f"tk:{t['id']}:0") for t in entries[:5]]
    prefix = f'tk_admin:{mode}' if admin else 'tk_user'
    if page:
        rows.append(button('← Назад', f'{prefix}:{page - 1}'))
    if len(entries) > 5:
        rows.append(button('Далее →', f'{prefix}:{page + 1}'))
    if admin:
        rows.append(button('Закрытые' if mode == 'active' else 'Активные',
                           'tk_admin:closed:0' if mode == 'active' else 'tk_admin:active:0'))
    rows.append(button('В админ-панель' if admin else 'В главное меню', 'admin_home' if admin else 'back_main'))
    title = 'Обращения покупателей' if admin else 'Мои обращения'
    await edit_message_safe(call, f'🛟 <b>{title}</b>\n\n' + ('Выберите обращение.' if entries else 'Обращений пока нет.'),
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)
