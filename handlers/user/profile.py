from utils.i18n import tr
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from database.db import get_user, get_referral_count, get_referral_settings
from keyboards.user_kb import _btn_text, profile_menu
from utils.nav import edit_message_safe, answer_safe
from utils import constants as c
from utils.emoji_map import EMOJI_COIN, EMOJI_HAND, EMOJI_STAR, EMOJI_USER_ALT

profile_router = Router()


@profile_router.callback_query(F.data == "my_profile")
async def my_profile(call: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await get_user(call.from_user.id)
    balance = float(user.get('balance', 0.0)) if user else 0.0
    ref_count = await get_referral_count(call.from_user.id)
    username = call.from_user.username or '—'
    text = tr("<tg-emoji emoji-id='5258362837411045098'>👤</tg-emoji> <b>Мой профиль</b>\n\n┏ <tg-emoji emoji-id='5258011929993026890'>👤</tg-emoji> <b>Пользователь:</b> <code>@{0}</code>\n┣ <tg-emoji emoji-id='5258476306152038031'>🔒</tg-emoji> <b>ID:</b> <code>{1}</code>\n┣ <tg-emoji emoji-id='5406841020769936275'>💵</tg-emoji> <b>Баланс:</b> <code>{2} ₽</code>\n┗ <tg-emoji emoji-id='{3}'>✋</tg-emoji> <b>Рефералов:</b> <code>{4}</code>", f'{username}', f'{call.from_user.id}', f'{balance:.2f}', f'{EMOJI_HAND}', f'{ref_count}')
    kb = await profile_menu()
    await edit_message_safe(call, text, reply_markup=kb)
    await answer_safe(call)


@profile_router.callback_query(F.data == "referral_info")
async def referral_info(call: CallbackQuery):
    settings = await get_referral_settings()
    count = await get_referral_count(call.from_user.id)
    bot_username = (await call.bot.me()).username
    ref_link = f'https://t.me/{bot_username}?start=ref_{call.from_user.id}'
    text = tr("<tg-emoji emoji-id='{0}'>⭐️</tg-emoji> <b>Реферальная система</b>\n\n<b>Скидка приглашённым:</b> {1}%\n<b>Бонус рефереру:</b> {2}%\n<b>Количество рефералов:</b> {3}\n\n<b>Ваша реферальная ссылка:</b>\n<code>{4}</code>\n\n<i>Делитесь ссылкой с друзьями. При каждой покупке реферала вы получаете бонус!</i>", f'{EMOJI_STAR}', f"{settings['discount_pct']:.0f}", f"{settings['bonus_pct']:.0f}", f'{count}', f'{ref_link}')
    label_back, emoji_back = await _btn_text('btn_back_profile', tr('« Назад'), c.BTN_ICON_BACK_SMILE)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label_back, callback_data='my_profile', icon_custom_emoji_id=emoji_back)]])
    await edit_message_safe(call, text, reply_markup=kb)
    await answer_safe(call)
