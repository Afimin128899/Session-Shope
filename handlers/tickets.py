"""Persistent conversations shared by customers and the support team."""
from utils.i18n import tr
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
        raise ValueError(tr('Некорректный номер обращения.'))
    number = int(value)
    if not 0 < number <= 9223372036854775807:
        raise ValueError(tr('Некорректный номер обращения.'))
    return number


def button(text, data):
    from utils.button_icons import decorate
    markup = decorate(InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=text, callback_data=data),
    ]]))
    return markup.inline_keyboard[0]


def order_back(order_id):
    return InlineKeyboardMarkup(inline_keyboard=[button(tr('Назад к заказу'), f'open_purchase:{order_id}')])


async def notify(bot, recipients, ticket_id, text):
    for recipient in set(recipients):
        try:
            from utils.notification_language import recipient_language
            async with recipient_language(recipient):
                await bot.send_message(recipient, tr('{0}\nОбращение #{1}.', tr(text), ticket_id), reply_markup=InlineKeyboardMarkup(inline_keyboard=[button(tr('Открыть обращение'), f'tk:{ticket_id}:0')]))
        except Exception:
            logger.warning('Ticket alert delivery failed for recipient %s', recipient)


async def display_ticket(call, ticket_id, before_id=0):
    admin = is_admin(call.from_user.id)
    owner_id = None if admin else call.from_user.id
    ticket = await store.get_ticket(ticket_id, owner_id)
    if not ticket:
        await answer_safe(call, tr('Обращение не найдено.'), show_alert=True)
        return
    messages = await store.history(ticket_id, owner_id, before_id)
    text = tr('🛟 <b>Обращение #{0} · заказ #{1}</b>\nСтатус: <b>{2}</b>\n\n', f"{ticket['id']}", f"{ticket['purchase_id'] or tr('Общий вопрос')}", f"{tr(TICKET_STATUSES.get(ticket['status'], tr('Неизвестен')))}")
    if not ticket['purchase_id']:
        text=tr('🛟 <b>Обращение #{0} · Общий вопрос</b>\nСтатус: <b>{1}</b>\n\n',ticket['id'],tr(TICKET_STATUSES.get(ticket['status'],'Неизвестен')))
    if ticket.get('warranty_claimed_at'):
        text += tr('🛡 Гарантийное обращение: принято в пределах срока.\n\n')
    if messages:
        item = messages[0]
        author = {'admin': tr('Поддержка'), 'user': tr('Покупатель'), 'system': tr('Система')}[item['author_role']]
        created = item['created_at'].replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Europe/Moscow'))
        text += tr('<b>{0} · {1} МСК</b>\n{2}', f'{author}', f'{created:%d.%m.%Y %H:%M}', f"{escape(item['body'])}")
    else:
        text += tr('Сообщений на этой странице нет.')
    reply_label = tr('Открыть снова и написать') if ticket['status'] == 'closed' else tr('Ответить')
    rows = [button(reply_label, f'tk_reply:{ticket_id}')]
    if messages and messages[0].get('photo_id'):
        rows.insert(0, button(tr('Открыть скриншот'), f"tk_photo:{messages[0]['id']}"))
    if len(messages) > 1:
        rows.append(button(tr('Предыдущее сообщение'), f"tk:{ticket_id}:{messages[0]['id']}"))
    rows.append(button(tr('К последнему сообщению / Обновить'), f'tk:{ticket_id}:0'))
    if admin:
        if ticket['status'] != 'closed':
            rows.append(button(tr('Закрыть обращение'), f'tk_close:{ticket_id}'))
        rows.append(button(tr('К обращениям'), 'tk_admin:active:0'))
    else:
        if ticket['purchase_id']:
            rows.append(button(tr('Назад к заказу'), f"open_purchase:{ticket['purchase_id']}"))
        rows.append(button(tr('Мои обращения'), 'tk_user:0'))
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
        await answer_safe(call, tr('Покупка не найдена.'), show_alert=True)
        return
    await state.clear()
    ticket = await store.ticket_for_order(order_id, call.from_user.id)
    if ticket:
        await display_ticket(call, ticket['id'])
    else:
        await state.update_data(ticket_order_id=order_id)
        await state.set_state(TicketInput.new)
        await edit_message_safe(call, tr('🛟 <b>Помощь по заказу #{0}</b>\n\nОпишите проблему текстом (до 500 символов). Переписка сохранится в боте. Не отправляйте пароли, коды входа и данные сессий.', f'{order_id}'), reply_markup=order_back(order_id))
    await answer_safe(call)


@ticket_router.callback_query(F.data.startswith('tk:'))
async def open_ticket(call, state):
    try:
        _, value, before = call.data.split(':')
        ticket_id = identifier(value)
        before_id = identifier(before) if before != '0' else 0
    except ValueError:
        await answer_safe(call, tr('Некорректный номер обращения.'), show_alert=True)
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
        await answer_safe(call, tr('Обращение не найдено.'), show_alert=True)
        return
    await state.clear()
    await state.update_data(ticket_id=ticket_id)
    await state.set_state(TicketInput.reply)
    await edit_message_safe(call, tr('Введите ответ по обращению #{0} (до 500 символов).\nЕсли обращение закрыто, сообщение откроет его снова. Не отправляйте пароли и коды входа.', f'{ticket_id}'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[button(tr('Отмена'), f'tk:{ticket_id}:0')]))
    await answer_safe(call)


@ticket_router.message(TicketInput.new)
async def submit_ticket(message, state):
    try:
        data = await state.get_data()
        order_id = data.get('ticket_order_id')
        if order_id is None:
            raise ValueError(tr('Выберите заказ в разделе «Мои покупки».'))
        ticket_id = await store.create_ticket(message.from_user.id, order_id, message.text or getattr(message, 'caption', None) or (tr('Скриншот проблемы') if getattr(message, 'photo', None) else ''), **{'photo': message.photo[-1].file_id} if getattr(message, 'photo', None) else {})
    except ValueError as exc:
        await message.answer(escape(str(exc)))
        return
    except Exception:
        logger.exception('Failed to save support message for user %s', message.from_user.id)
        await message.answer(tr('Не удалось сохранить сообщение. Попробуйте отправить его ещё раз позже.'))
        return
    await state.clear()
    await message.answer(tr('✅ Обращение #{0} сохранено. Поддержка ответит здесь, в боте.', f'{ticket_id}'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[button(tr('Открыть обращение'), f'tk:{ticket_id}:0')]))
    await notify(message.bot, ADMIN_IDS, ticket_id, 'Новое сообщение покупателя.')


@ticket_router.message(TicketInput.reply)
async def submit_reply(message, state):
    admin = is_admin(message.from_user.id)
    try:
        data = await state.get_data()
        ticket_id = data.get('ticket_id')
        if ticket_id is None:
            raise ValueError(tr('Откройте обращение заново.'))
        user_id = await store.reply(ticket_id, message.from_user.id, message.text or getattr(message, 'caption', None) or (tr('Скриншот проблемы') if getattr(message, 'photo', None) else ''), admin=admin, **{'photo': message.photo[-1].file_id} if getattr(message, 'photo', None) else {})
    except ValueError as exc:
        await message.answer(escape(str(exc)))
        return
    except Exception:
        logger.exception('Failed to save support message for user %s', message.from_user.id)
        await message.answer(tr('Не удалось сохранить сообщение. Попробуйте отправить его ещё раз позже.'))
        return
    await state.clear()
    await message.answer(tr('✅ Сообщение сохранено.'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[button(tr('К переписке'), f'tk:{ticket_id}:0')]))
    await notify(message.bot, [user_id] if admin else ADMIN_IDS, ticket_id, tr('Поддержка ответила на ваше обращение.') if admin else tr('Новое сообщение покупателя.'))


@ticket_router.callback_query(F.data.startswith('tk_close:'))
async def close_ticket(call, state):
    if not is_admin(call.from_user.id):
        await answer_safe(call, tr('Доступ запрещён.'), show_alert=True)
        return
    try:
        ticket_id = identifier(call.data.split(':', 1)[1])
        user_id = await store.close_ticket(ticket_id, call.from_user.id)
    except ValueError as exc:
        await answer_safe(call, str(exc), show_alert=True)
        return
    await state.clear()
    await display_ticket(call, ticket_id)
    await answer_safe(call, tr('Обращение закрыто.'))
    if user_id is not None:
        await notify(call.bot, [user_id], ticket_id, 'Поддержка закрыла ваше обращение.')


@ticket_router.callback_query(F.data.startswith('tk_user:') | F.data.startswith('tk_admin:'))
async def show_inbox(call, state):
    try:
        parts = call.data.split(':')
        admin = parts[0] == 'tk_admin'
        if admin and (not is_admin(call.from_user.id)):
            await answer_safe(call, tr('Доступ запрещён.'), show_alert=True)
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
        await answer_safe(call, tr('Некорректная страница.'), show_alert=True)
        return
    entries = await store.inbox(None if admin else call.from_user.id, mode == 'closed', page)
    await state.clear()
    rows = [button(tr('#{0} · заказ #{1} · {2}', f"{t['id']}", f"{t['purchase_id'] or tr('Общий вопрос')}", f"{tr(TICKET_STATUSES.get(t['status'], ''))}"), f"tk:{t['id']}:0") for t in entries[:5]]
    prefix = f'tk_admin:{mode}' if admin else 'tk_user'
    if page:
        rows.append(button(tr('← Назад'), f'{prefix}:{page - 1}'))
    if len(entries) > 5:
        rows.append(button(tr('Далее →'), f'{prefix}:{page + 1}'))
    if admin:
        rows.append(button(tr('Закрытые') if mode == 'active' else tr('Активные'), 'tk_admin:closed:0' if mode == 'active' else 'tk_admin:active:0'))
    rows.append(button(tr('В админ-панель') if admin else tr('Мой профиль'), 'admin_home' if admin else 'my_profile'))
    title = tr('Обращения покупателей') if admin else tr('Мои обращения')
    await edit_message_safe(call, f'🛟 <b>{title}</b>\n\n' + (tr('Выберите обращение.') if entries else tr('Обращений пока нет.')), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)


@ticket_router.callback_query(F.data.startswith('tk_photo:'))
async def view_photo(call):
    from database.db import _get_pool
    import aiomysql
    try:
        message = identifier(call.data.split(':')[1])
    except ValueError:
        await call.answer(tr('Некорректный ID'))
        return
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute('SELECT m.photo_id FROM support_messages m JOIN support_tickets t ON t.id=m.ticket_id WHERE m.id=%s' + ('' if is_admin(call.from_user.id) else ' AND t.user_id=%s'), (message,) if is_admin(call.from_user.id) else (message, call.from_user.id))
            row = await cur.fetchone()
    if not row or not row['photo_id']:
        await call.answer(tr('Вложение недоступно'), show_alert=True)
        return
    await call.message.answer_photo(row['photo_id'])
    await call.answer()
