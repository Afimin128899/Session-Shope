"""Direct private messages between any user and configured administrators.

No ticket creation, status tracking or purchase requirement. Telegram keeps the
conversation; the reply button carries the verified recipient across restarts.
"""
import asyncio
import logging
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_IDS
from database import db, quality
from utils.i18n import tr
from utils.nav import answer_safe, edit_message_safe

logger = logging.getLogger(__name__)
support_router = Router()
support_router.message.filter(F.chat.type == 'private')
support_router.callback_query.filter(F.message.chat.type == 'private')


class DirectSupport(StatesGroup):
    message = State()
    reply = State()


def cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=tr('Завершить переписку'), callback_data='support_end'),
    ]])


def reply_keyboard(user_id):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=tr('Ответить пользователю'), callback_data=f'support_reply:{user_id}'),
    ]])


def copyable(message):
    # Never consume successful_payment, refunded_payment or other service events.
    return message.content_type in {'text', 'photo', 'document', 'video', 'animation', 'audio', 'voice', 'video_note', 'sticker', 'contact', 'location'} and not (message.text or '').startswith('/')


async def begin(event, state, *, order=None, warranty=False, command=False):
    await state.clear()
    await state.update_data(support_order=order, support_warranty=warranty)
    await state.set_state(DirectSupport.message)
    text = tr('<b>Техподдержка</b>\n\nОтправьте сообщение или вложение — оно будет передано администрации. Ответ придёт сюда. Покупка для связи с поддержкой не требуется.\n\nНе отправляйте пароли, коды входа и файлы сессий.')
    if order:
        text += tr('\n\nЗаказ #{0}.', order)
    if warranty:
        text += tr('\nСрок гарантии проверяется при отправке сообщения.')
    if command:
        from utils.section_banners import answer_screen
        await answer_screen(event, text, section='support', reply_markup=cancel_keyboard())
    else:
        await edit_message_safe(event, text, section='support', reply_markup=cancel_keyboard())
        await answer_safe(event)


@support_router.message(Command('support'))
async def support_command(message, state):
    await begin(message, state, command=True)


@support_router.callback_query(F.data == 'support')
async def support(call, state):
    await begin(call, state)


@support_router.callback_query(F.data.startswith('purchase_help:'))
async def purchase_help(call, state):
    raw = call.data.split(':', 1)[1]
    if not raw.isascii() or not raw.isdigit() or len(raw) > 10 or not 0 < int(raw) <= 2147483647:
        return await answer_safe(call, tr('Покупка не найдена.'), show_alert=True)
    order = int(raw)
    if not await db.get_purchase_for_user(order, call.from_user.id):
        return await answer_safe(call, tr('Покупка не найдена.'), show_alert=True)
    await begin(call, state, order=order)


@support_router.callback_query(F.data.startswith(('tk_', 'tk:')))
async def legacy_support(call, state):
    # Old inline buttons must not reopen archived tickets or mutate their data.
    await begin(call, state)


@support_router.callback_query(F.data == 'support_end')
async def end_support(call, state):
    await state.clear()
    await call.message.answer(tr('Переписка завершена. Для меню отправьте /menu.'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=tr('Главное меню'), callback_data='back_main'),
    ]]))
    await answer_safe(call)


async def relay(message, *, order=None, warranty=False):
    if warranty:
        row = await db.get_purchase_for_user(order, message.from_user.id)
        if not row or not quality.warranty(row)['active']:
            await message.answer(tr('Гарантия не действует. Напишите /support для обычной поддержки.'))
            return False
    user = message.from_user
    name = escape(user.full_name or str(user.id))
    username = '@' + escape(user.username) if user.username else tr('без имени пользователя')
    context = tr('<b>Сообщение в поддержку</b>\n{0} · {1}\nID: <code>{2}</code>', name, username, user.id)
    if order:
        context += tr('\nЗаказ #{0}.', order)
    if warranty:
        context += tr('\nГарантия действует на момент отправки.')
    delivered = 0
    for admin in sorted(set(ADMIN_IDS)):
        try:
            await asyncio.wait_for(message.bot.send_message(admin, context, parse_mode='HTML', reply_markup=reply_keyboard(user.id)), timeout=15)
            await asyncio.wait_for(message.bot.copy_message(chat_id=admin, from_chat_id=message.chat.id, message_id=message.message_id), timeout=15)
            delivered += 1
        except Exception as exc:
            logger.warning('Direct support delivery failed [%s], recipient=%s', type(exc).__name__, admin)
    if delivered:
        try:
            from database.direct_chat import append
            await append(user.id,'user',(message.text or message.caption or ('Вложение: '+str(message.content_type)))[:4000])
        except Exception: logger.warning('Direct chat history save unavailable')
        await message.answer(tr('Сообщение передано администрации. Ответ придёт в этот чат.'), reply_markup=cancel_keyboard())
        return True
    await message.answer(tr('Сообщение не удалось передать. Попробуйте позже.'), reply_markup=cancel_keyboard())
    return False


@support_router.message(DirectSupport.message, copyable)
async def user_message(message, state):
    data = await state.get_data()
    await relay(message, order=data.get('support_order'), warranty=data.get('support_warranty', False))


@support_router.callback_query(F.data.startswith('support_reply:'))
async def begin_reply(call, state):
    if call.from_user.id not in ADMIN_IDS:
        return await answer_safe(call, tr('Нет доступа.'), show_alert=True)
    raw = call.data.split(':', 1)[1]
    if not raw.isascii() or not raw.isdigit() or len(raw) > 16 or not 0 < int(raw) <= 4503599627370495:
        return await answer_safe(call, tr('Некорректный пользователь.'), show_alert=True)
    await state.clear()
    await state.update_data(support_recipient=int(raw))
    await state.set_state(DirectSupport.reply)
    # A separate prompt preserves the user's original message and attachments.
    await call.message.answer(tr('Отправьте ответ пользователю {0}. Для отмены — /cancel.', raw), reply_markup=cancel_keyboard())
    await answer_safe(call)


@support_router.message(DirectSupport.reply, copyable)
async def admin_message(message, state):
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        return
    target = (await state.get_data()).get('support_recipient')
    if type(target) is not int or not 0 < target <= 4503599627370495:
        await state.clear()
        return
    try:
        await message.bot.send_message(target, tr('<b>Ответ поддержки</b>'), parse_mode='HTML', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=tr('Написать в поддержку'), callback_data='support'),
        ]]))
        await message.bot.copy_message(chat_id=target, from_chat_id=message.chat.id, message_id=message.message_id)
    except Exception as exc:
        logger.warning('Direct support reply failed [%s], recipient=%s', type(exc).__name__, target)
        await message.answer(tr('Не удалось доставить ответ. Пользователь мог заблокировать бота.'))
        return
    try:
        from database.direct_chat import append
        await append(target,'admin',(message.text or message.caption or ('Вложение: '+str(message.content_type)))[:4000])
    except Exception: logger.warning('Direct chat history save unavailable')
    await message.answer(tr('Ответ отправлен пользователю {0}.', target), reply_markup=cancel_keyboard())
