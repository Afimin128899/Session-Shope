from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from database.db import get_user, get_referral_count, get_referral_settings
from keyboards.user_kb import _btn_text
from utils.nav import edit_message_safe, answer_safe
from utils import constants as c
from utils.emoji_map import EMOJI_COIN, EMOJI_HAND, EMOJI_STAR, EMOJI_USER_ALT

profile_router = Router()


@profile_router.callback_query(F.data == "my_profile")
async def my_profile(call: CallbackQuery):
    user = await get_user(call.from_user.id)
    bal_usdt = float(user.get("balance_usdt", 0.0)) if user else 0.0
    ref_count = await get_referral_count(call.from_user.id)
    username = call.from_user.username or "—"

    text = (
        "<tg-emoji emoji-id='5258362837411045098'>👤</tg-emoji> <b>Мой профиль</b>\n\n"
        f"┏ <tg-emoji emoji-id='5258011929993026890'>👤</tg-emoji> <b>Пользователь:</b> <code>@{username}</code>\n"
        f"┣ <tg-emoji emoji-id='5258476306152038031'>🔒</tg-emoji> <b>ID:</b> <code>{call.from_user.id}</code>\n"
        f"┣ <tg-emoji emoji-id='5406841020769936275'>💵</tg-emoji> <b>Баланс:</b> <code>{bal_usdt:.2f} USDT ($)</code>\n"
        f"┗ <tg-emoji emoji-id='{EMOJI_HAND}'>✋</tg-emoji> <b>Рефералов:</b> <code>{ref_count}</code>"
    )

    label_ref, emoji_ref = await _btn_text("btn_referral_system", "Реферальная система", EMOJI_HAND)
    label_back, emoji_back = await _btn_text("btn_back_profile", "« Назад", c.BTN_ICON_BACK_SMILE)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label_ref, callback_data="referral_info", icon_custom_emoji_id=emoji_ref)],
        [InlineKeyboardButton(text=label_back, callback_data="back_main", icon_custom_emoji_id=emoji_back)],
    ])

    await edit_message_safe(call, text, reply_markup=kb)
    await answer_safe(call)


@profile_router.callback_query(F.data == "referral_info")
async def referral_info(call: CallbackQuery):
    settings = await get_referral_settings()
    count = await get_referral_count(call.from_user.id)
    bot_username = (await call.bot.me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref_{call.from_user.id}"

    text = (
        f"<tg-emoji emoji-id='{EMOJI_STAR}'>⭐️</tg-emoji> <b>Реферальная система</b>\n\n"
        f"<b>Ваша скидка:</b> {settings['discount_pct']:.0f}%\n"
        f"<b>Бонус рефереру:</b> {settings['bonus_pct']:.0f}%\n"
        f"<b>Количество рефералов:</b> {count}\n\n"
        f"<b>Ваша реферальная ссылка:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        f"<i>Делитесь ссылкой с друзьями. При каждой покупке реферала вы получаете бонус!</i>"
    )

    label_back, emoji_back = await _btn_text("btn_back_profile", "« Назад", c.BTN_ICON_BACK_SMILE)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label_back, callback_data="my_profile", icon_custom_emoji_id=emoji_back)],
    ])

    await edit_message_safe(call, text, reply_markup=kb)
    await answer_safe(call)
