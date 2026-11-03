"""Preview and confirm broadcasts, send in bounded batches, allow stopping."""
import asyncio
from datetime import datetime
import secrets
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import ADMIN_IDS
from database.db import _get_pool, log_broadcast
from utils.actions import single_action
from utils.nav import answer_safe, edit_message_safe

broadcast_router = Router()
_jobs = {}


class BroadcastState(StatesGroup):
    waiting_content = State()
    waiting_button = State()
    waiting_confirm = State()


def is_admin(user_id):
    return user_id in ADMIN_IDS


def _markup_from_spec(spec):
    spec = spec.strip()
    if spec == '-':
        return None
    label, separator, url = spec.partition('|')
    label, url = label.strip(), url.strip()
    parsed = urlsplit(url)
    if not separator or not 1 <= len(label) <= 64 or len(url) > 2048 or parsed.scheme not in {'https', 'http'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Введите Подпись|https://ссылка (подпись до 64 символов) или - без кнопки.')
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, url=url)]])


async def recipients(after=0, ceiling=None):
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            if ceiling is None:
                await cur.execute('SELECT COUNT(*),COALESCE(MAX(id),0) FROM users')
                return await cur.fetchone()
            await cur.execute('SELECT id FROM users WHERE id>%s AND id<=%s ORDER BY id LIMIT 100', (after, ceiling))
            return [row[0] for row in await cur.fetchall()]


@broadcast_router.callback_query(F.data == 'admin_broadcast')
async def broadcast_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await answer_safe(call)
        return
    if call.from_user.id in _jobs:
        await answer_safe(call, 'Рассылка уже выполняется. Дождитесь окончания или нажмите «Остановить».', show_alert=True)
        return
    await state.clear()
    await state.set_state(BroadcastState.waiting_content)
    await edit_message_safe(call, 'Отправьте текст или фото с подписью. Перед отправкой будет предпросмотр и подтверждение. Отмена: /cancel.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Отмена', callback_data='admin_home')]]))
    await answer_safe(call)


@broadcast_router.message(BroadcastState.waiting_content)
async def broadcast_got_content(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if not message.text and not message.photo:
        await message.answer('Нужен текст или фото. Отмена: /cancel.')
        return
    await state.update_data(bc_source_chat=message.chat.id, bc_source_msg=message.message_id)
    await state.set_state(BroadcastState.waiting_button)
    await message.answer('Кнопка: <code>Подпись|https://ссылка</code>\nИли <code>-</code> без кнопки.')


@broadcast_router.message(BroadcastState.waiting_button, F.text)
async def broadcast_preview(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    try:
        markup = _markup_from_spec(message.text)
    except ValueError as exc:
        await message.answer(str(exc))
        return
    data = await state.get_data()
    await bot.copy_message(chat_id=message.chat.id, from_chat_id=data['bc_source_chat'], message_id=data['bc_source_msg'], reply_markup=markup)
    count, _ = await recipients()
    token = secrets.token_urlsafe(6)
    await state.update_data(bc_spec=message.text, bc_token=token)
    await state.set_state(BroadcastState.waiting_confirm)
    await message.answer(f'Это предпросмотр. Пользователей сейчас: {count}. Отправить рассылку?',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='Подтвердить отправку', callback_data='bc_send:' + token)],
            [InlineKeyboardButton(text='Отмена', callback_data='admin_home')],
        ]))


@broadcast_router.callback_query(F.data.startswith('bc_stop:'))
async def stop_broadcast(call: CallbackQuery):
    job = _jobs.get(call.from_user.id)
    if is_admin(call.from_user.id) and job and job['token'] == call.data.split(':', 1)[1]:
        job['stop'] = True
        await answer_safe(call, 'Остановим после текущей отправки.')
    else:
        await answer_safe(call, 'Рассылка уже закончилась или недоступна.')


@broadcast_router.callback_query(F.data.startswith('bc_send:'))
async def broadcast_run(call: CallbackQuery, state: FSMContext, bot: Bot):
    if not is_admin(call.from_user.id):
        await answer_safe(call)
        return
    async with single_action(call.from_user.id, 'broadcast') as acquired:
        if not acquired:
            await answer_safe(call, 'Рассылка уже выполняется.')
            return
        data = await state.get_data()
        if not data.get('bc_token') or data['bc_token'] != call.data.split(':', 1)[1]:
            await answer_safe(call, 'Подтверждение устарело. Создайте рассылку заново.', show_alert=True)
            return
        markup = _markup_from_spec(data['bc_spec'])
        total, ceiling = await recipients()
        await state.clear()
        job = {'token': data['bc_token'], 'stop': False}
        _jobs[call.from_user.id] = job
        ok = failed = after = 0
        try:
            await answer_safe(call, 'Рассылка началась.')
            await call.message.answer(f'Рассылка началась. Получателей: {total}.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text='Остановить рассылку', callback_data='bc_stop:' + job['token']),
            ]]))
            while not job['stop']:
                batch = await recipients(after, ceiling)
                if not batch:
                    break
                for user_id in batch:
                    if job['stop']:
                        break
                    after = user_id
                    try:
                        for attempt in range(2):
                            try:
                                await bot.copy_message(chat_id=user_id, from_chat_id=data['bc_source_chat'], message_id=data['bc_source_msg'], reply_markup=markup)
                                ok += 1
                                break
                            except TelegramRetryAfter as exc:
                                if attempt or exc.retry_after > 30:
                                    raise
                                await asyncio.sleep(exc.retry_after)
                                if job['stop']:
                                    break
                    except Exception:
                        failed += 1
                    await asyncio.sleep(0.05)
            await log_broadcast(call.from_user.id, datetime.now(ZoneInfo('Europe/Moscow')).strftime('%Y-%m-%d %H:%M:%S'), total, ok, failed,
                                ('Остановлена' if job['stop'] else 'Завершена') + ': ' + data['bc_spec'][:160])
            await call.message.answer(f"Рассылка {'остановлена' if job['stop'] else 'завершена'}.\nДоставлено: {ok}\nОшибок: {failed}\nНе отправлено: {max(0,total-ok-failed)}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='В админ-панель', callback_data='admin_home')]]))
        finally:
            _jobs.pop(call.from_user.id, None)
