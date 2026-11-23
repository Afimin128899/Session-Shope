"""Separate private admin tool; no sales/stock/payment handlers are called."""
import asyncio
import shutil
import uuid
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from services import admin_session_runtime as runtime
from services.admin_session_workbench.files import ingest
from services.admin_session_workbench.engine import session_fingerprint
from services.admin_session_workbench.policy import CLEANUP_CONFIRMATION
from services.admin_session_workbench.pr1_input import normalize_code

router = Router(name='admin-session-workbench')
LIMIT = 20 * 1024 * 1024
PREFIX = 'session_tool:'
STATES = {'draft':'ждёт подтверждения', 'queued':'в очереди', 'running':'выполняется', 'done':'готово',
          'failed':'ошибка', 'blocked':'ограничение Telegram', 'cancelled':'отменена',
          'interrupted':'прервана перезапуском', 'expired':'срок хранения истёк'}


UPLOAD_ERRORS = {
    'Превышен размер загрузки', 'Слишком большой архив', 'Небезопасный путь ZIP',
    'Нужны уникальные пары .session + .json в корне ZIP', 'Превышен размер распаковки',
    'Разрешены .session и .zip', 'Сессии не найдены', 'Неверный формат Telethon session',
    'Нет парного JSON', 'JSON должен быть объектом',
}


class SessionToolState(StatesGroup):
    upload = State()


def menu():
    rows = [[('Загрузить .session / ZIP','upload')], [('Статус','status'),('Мои результаты','archives')],
            [('Пауза','pause'),('Продолжить очередь','resume')], [('Отменить мои задачи','cancel')]]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=PREFIX+action) for text, action in row] for row in rows
    ] + [[InlineKeyboardButton(text='В админку', callback_data='admin_home')]])


def confirmation(ident):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='Подтверждаю действия', callback_data=PREFIX+'confirm:'+ident, style='danger'),
        InlineKeyboardButton(text='Отменить', callback_data=PREFIX+'cancel:'+ident),
    ]])


async def access(event):
    import config
    from utils.partner_context import CURRENT
    message = event.message if isinstance(event, CallbackQuery) else event
    allowed = (message is not None and message.chat.type == 'private' and event.from_user is not None
               and event.from_user.id in config.ADMIN_IDS and CURRENT.get() is None)
    # Partner bots share the dispatcher, but cannot invoke the root bot's tool.
    if allowed:
        try:
            active = runtime.current()
            allowed = event.bot.id == active.bot_id
        except RuntimeError:
            allowed = getattr(event.bot, 'token', None) == config.BOT_TOKEN
    if not allowed:
        if isinstance(event, CallbackQuery):
            await event.answer('Доступ только администратору в личном чате основного бота.', show_alert=True)
        return False
    return True


async def get_workbench(message):
    try:
        return runtime.current()
    except RuntimeError as exc:
        await message.answer(str(exc), parse_mode=None)
        return None


async def open_tool(message, state):
    current_state = await state.get_state()
    if current_state and current_state != SessionToolState.upload.state:
        await message.answer('Сначала завершите текущий диалог магазина или отмените его через /cancel.', parse_mode=None)
        return
    await state.clear()
    await message.answer(
        'Новая сессия → очистка → выход из старой\n\n'
        'Загрузите исходную .session или ZIP с парными JSON. Номер вводить не нужно — бот получает его из исходной сессии.\n\n'
        '1/4 — подключение к исходной сессии\n'
        '2/4 — запрос и получение кода\n'
        '3/4 — вход в новую авторизацию и сохранение\n'
        '4/4 — очистка, сохранение результата и выход из старой\n\n'
        'Перед обработкой будет показан полный список действий. Новые сессии сохраняются, а выход выполняется только из загруженной старой авторизации. '
        'Инструмент не добавляет результат в товары и не обновляет сохранённые сессии магазина. '
        'Если исходная сессия используется товаром магазина, её отзыв сделает ту копию нерабочей.\n\n'
        'Проверка формата кода основана на Session PR #1. Telegram определяет доставку кода. '
        'Для ручного ввода используйте /session_tool_input ID значение.', reply_markup=menu(), parse_mode=None)


@router.message(Command('session_tool'))
async def command_open(message: Message, state: FSMContext):
    if await access(message):
        await open_tool(message, state)


@router.callback_query(F.data.startswith(PREFIX))
async def callback(call: CallbackQuery, state: FSMContext):
    if not await access(call):
        return
    await call.answer()
    action, _, ident = call.data[len(PREFIX):].partition(':')
    if action == 'open':
        await open_tool(call.message, state)
        return
    active = await get_workbench(call.message)
    if active is None:
        return
    owner = call.from_user.id
    if action == 'upload':
        await state.set_state(SessionToolState.upload)
        await call.message.answer('Отправьте свою .session или ZIP с парами .session + .json, до 20 МБ.', parse_mode=None)
    elif action == 'review':
        job = active.store.get(ident, owner)
        if job and job['mode'] == 'migrate_clean' and job['state'] == 'draft':
            await call.message.answer(f'Задача {ident}\n\n{CLEANUP_CONFIRMATION}', reply_markup=confirmation(ident), parse_mode=None)
        else:
            await call.message.answer('Задача недоступна для подтверждения.', parse_mode=None)
    elif action == 'confirm':
        job = active.store.get(ident, owner)
        if not job or job['mode'] != 'migrate_clean' or job['state'] != 'draft':
            await call.message.answer('Задача недоступна или уже подтверждена.', parse_mode=None)
            return
        active.store.update(ident, state='queued', stage='Подтверждено администратором')
        await call.message.answer(f'Задача {ident} поставлена в очередь.', reply_markup=menu(), parse_mode=None)
    elif action == 'cancel':
        if ident and active.store.get(ident, owner) is None:
            await call.message.answer('Задача недоступна.', parse_mode=None)
            return
        active.engine.cancel(owner, ident or None)
        if await state.get_state() == SessionToolState.upload.state:
            await state.clear()
        await call.message.answer('Отмена запрошена. Выполненные действия Telegram не откатываются; новые сохранённые файлы остаются.', reply_markup=menu(), parse_mode=None)
    elif action in {'pause','resume'}:
        active.store.pause(owner, action == 'pause')
        await call.message.answer('Запуск очереди приостановлен.' if action == 'pause' else 'Очередь продолжена.', reply_markup=menu(), parse_mode=None)
    elif action == 'status':
        jobs = active.store.rows(owner)[:20]
        text = '\n'.join(f"{job['id']}: {STATES.get(job['state'], job['state'])} — {job['stage']}" for job in jobs)
        controls = menu().inline_keyboard
        controls = [[InlineKeyboardButton(text=f'Действия для {job["id"]}', callback_data=PREFIX+'review:'+job['id'])]
                    for job in jobs if job['state'] == 'draft'] + controls
        await call.message.answer(text[:3900] or 'Задач нет.', reply_markup=InlineKeyboardMarkup(inline_keyboard=controls), parse_mode=None)
    elif action == 'archives':
        active.store.recover_new_sessions(owner)
        jobs = [job for job in active.store.rows(owner) if job['result'] and Path(job['result']).is_file()]
        if not jobs:
            await call.message.answer('Сохранённых результатов нет.', reply_markup=menu(), parse_mode=None)
        for job in jobs:
            await active.engine.deliver(job)


@router.message(SessionToolState.upload, F.document)
async def upload(message: Message, state: FSMContext):
    if not await access(message):
        return
    active = await get_workbench(message)
    if active is None:
        return
    document = message.document
    suffix = Path(document.file_name or '').suffix.lower()
    if suffix not in {'.session','.zip'} or not document.file_size or document.file_size > LIMIT:
        await message.answer('Нужен непустой .session или ZIP размером до 20 МБ.', parse_mode=None)
        return
    staging = active.root / 'staging' / uuid.uuid4().hex
    staging.mkdir(parents=True, mode=0o700)
    try:
        path = staging / ('upload'+suffix)
        await message.bot.download(document, destination=path)
        entries = ingest(path, staging / 'extracted', LIMIT)
        created = []
        for session, config in entries:
            folder = active.root / 'uploads' / uuid.uuid4().hex
            folder.mkdir(parents=True, mode=0o700)
            target = folder / 'account.session'
            shutil.copyfile(session, target)
            try:
                ident = active.store.add(message.from_user.id, session_fingerprint(target), target, config, 'migrate_clean', state='draft')
                active.store.update(ident, state='draft', stage='Ожидание подтверждения полного списка действий')
            except Exception:
                shutil.rmtree(folder, ignore_errors=True)
                raise
            created.append(ident)
        await state.clear()
        for ident in created:
            await message.answer(f'Задача {ident}\n\n{CLEANUP_CONFIRMATION}', reply_markup=confirmation(ident), parse_mode=None)
    except Exception as exc:
        # Never echo exceptions: ZIP/JSON/SQLite messages may contain secrets.
        hint = str(exc) if type(exc) is ValueError and str(exc) in UPLOAD_ERRORS else f'Ошибка {type(exc).__name__}; проверьте формат и статус задач'
        await message.answer(f'Файл не принят или уведомление не доставлено: {hint}.', reply_markup=menu(), parse_mode=None)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


@router.message(Command('session_tool_input'))
async def manual_input(message: Message):
    if not await access(message):
        return
    active = await get_workbench(message)
    if active is None:
        return
    parts = (message.text or '').split(maxsplit=2)
    accepted = False
    if len(parts) == 3:
        owner, ident, value = message.from_user.id, parts[1], parts[2]
        pending = active.engine.inputs.get((owner, ident))
        if pending:
            kind = pending[0]
            if kind == 'code':
                value = value.strip()
                if value != 'resend':
                    value = normalize_code(value)
                    if value and not value.isascii():
                        value = None
            elif kind == 'password':
                value = value.strip() or None
            if value:
                accepted = active.engine.answer(owner, ident, value)
    try:
        await message.delete()
    except Exception:
        pass
    await message.answer('Ответ передан задаче.' if accepted else 'Нет ожидающего ввода для этой задачи или неверный формат. /session_tool_input ID значение', parse_mode=None)
