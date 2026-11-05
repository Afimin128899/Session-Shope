from utils.i18n import tr
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.preferences import set_language
from utils.i18n import LANGUAGE
from utils.nav import edit_message_safe, answer_safe

language_router = Router()


def language_menu():
    active = LANGUAGE.get()
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=('✓ ' if active == 'ru' else '') + tr('🇷🇺 Русский'), callback_data='language:ru'), InlineKeyboardButton(text=('✓ ' if active == 'en' else '') + '🇬🇧 English', callback_data='language:en')], [InlineKeyboardButton(text=tr('Мой профиль'), callback_data='my_profile')]])


@language_router.message(Command('language'))
async def language_command(message):
    await message.answer(tr('🌐 Язык / Language'), reply_markup=language_menu())


@language_router.callback_query(F.data == 'language')
async def choose_language(call):
    await edit_message_safe(call, tr('🌐 <b>Язык / Language</b>\n\nНастройка общая для бота и Mini App.'), reply_markup=language_menu(), section='profile')
    await answer_safe(call)


@language_router.callback_query(F.data.in_({'language:ru', 'language:en'}))
async def save_language(call, state):
    value = await set_language(call.from_user.id, call.data.split(':')[1])
    LANGUAGE.set(value)
    await state.clear()
    await edit_message_safe(call, tr('🌐 <b>Язык сохранён</b>\n\nБот и Mini App используют выбранный язык.'), reply_markup=language_menu(), section='profile')
    await answer_safe(call)
