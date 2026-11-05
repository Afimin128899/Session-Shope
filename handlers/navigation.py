"""Commands that remain available while a form is open, plus safe stale-button replies."""
from utils.i18n import tr
import asyncio
from contextlib import suppress
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ErrorEvent, Message

from keyboards.user_kb import main_menu
from utils.nav import answer_safe, ensure_user
from utils.section_banners import answer_screen

commands_router = Router()
fallback_router = Router()
logger = logging.getLogger(__name__)


@commands_router.message(Command('cancel', 'menu'))
async def cancel(message: Message, state: FSMContext):
    from utils.referral_link import complete
    await complete(message.from_user, state)
    await state.clear()
    from services.telethon_auth import remove_cached_client
    with suppress(Exception):
        await asyncio.wait_for(remove_cached_client(message.from_user.id), timeout=5)
    await ensure_user(message.from_user.id, message.from_user.username)
    await answer_screen(message, tr('Главное меню. Незавершённый ввод отменён.'), section='home', reply_markup=await main_menu(message.from_user.id))


@commands_router.callback_query(lambda call: call.data == 'page_info')
async def page_info(call: CallbackQuery):
    await answer_safe(call, tr('Для перехода используйте стрелки.'))


@fallback_router.callback_query()
async def stale_button(call: CallbackQuery):
    await answer_safe(call, tr('Кнопка устарела или недоступна. Отправьте /menu, чтобы открыть актуальное меню.'), show_alert=True)


@fallback_router.message()
async def unknown_message(message: Message, state: FSMContext):
    if await state.get_state():
        await message.answer(tr('Для этого шага нужен другой формат сообщения. Следуйте подсказке выше или отправьте /cancel.'))
    else:
        await message.answer(tr('Выберите действие в меню или отправьте /menu.'))


@commands_router.errors()
async def unexpected_error(event: ErrorEvent):
    logger.error('Bot action failed: %s', type(event.exception).__name__)
    text = tr('Не удалось завершить действие. Проверьте баланс, покупки или результат в админке перед повтором. Если проблема повторяется, напишите в поддержку.')
    if event.update.callback_query:
        await answer_safe(event.update.callback_query, text, show_alert=True)
    elif event.update.message:
        with suppress(Exception):
            await event.update.message.answer(text)
    return True
