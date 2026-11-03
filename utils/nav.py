"""Telegram navigation that keeps the previous screen if replacement delivery fails."""
import asyncio
import logging

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from database.db import create_user, get_user
from keyboards.user_kb import main_menu
from utils.emoji_map import EMOJI_WALLET, EMOJI_BACK

logger = logging.getLogger(__name__)


async def ensure_user(user_id: int, username: str | None = None) -> None:
    await create_user(user_id, username)


async def answer_safe(call: CallbackQuery, *args, **kwargs) -> None:
    try:
        await call.answer(*args, **kwargs)
    except Exception:
        # Callback acknowledgements expire; failing one must not repeat a mutation.
        logger.debug('Callback acknowledgement unavailable')


async def edit_message_safe(call: CallbackQuery, text: str, reply_markup=None, parse_mode: str = 'HTML') -> None:
    message = call.message
    options = dict(reply_markup=reply_markup, parse_mode=parse_mode)
    if message is None:
        if getattr(call, 'inline_message_id', None):
            await call.bot.edit_message_text(text=text, inline_message_id=call.inline_message_id, **options)
        return

    async def replace():
        # Publish first: an API failure must not destroy the customer's only screen.
        await message.answer(text, **options)
        try:
            await message.delete()
        except Exception:
            logger.debug('Old navigation message could not be removed')

    if getattr(message, 'photo', None):
        await replace()
        return
    for attempt in range(2):
        try:
            await message.edit_text(text, **options)
            return
        except TelegramRetryAfter as exc:
            if attempt or exc.retry_after > 2:
                raise
            await asyncio.sleep(exc.retry_after)
        except TelegramBadRequest as exc:
            reason = str(exc).lower()
            if 'message is not modified' in reason:
                return
            if any(part in reason for part in ('message to edit not found', "message can't be edited", 'message can not be edited', 'there is no text in the message')):
                await replace()
                return
            # Invalid HTML and transient errors belong to the central error handler.
            raise


async def edit_main(call: CallbackQuery) -> None:
    await ensure_user(call.from_user.id, call.from_user.username)
    await edit_message_safe(call, '<b>Главное меню магазина</b>\n\nВыберите раздел ниже.', reply_markup=await main_menu(call.from_user.id))


async def edit_balance(call: CallbackQuery, currency: str = 'USDT') -> None:
    await ensure_user(call.from_user.id, call.from_user.username)
    user = await get_user(call.from_user.id)
    balance = float(user['balance']) if user and 'balance' in user else 0.0
    text = f'<b>Мой кошелёк</b>\n\nБаланс: <b>{balance:.2f} ₽</b>\n\nПополнение подтверждается автоматически платёжным сервисом.'
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='Пополнить баланс', callback_data='topup_balance', icon_custom_emoji_id=EMOJI_WALLET)],
        [InlineKeyboardButton(text='Мой профиль', callback_data='my_profile', icon_custom_emoji_id=EMOJI_BACK)],
    ])
    await edit_message_safe(call, text, reply_markup=kb)
