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
    text = tr("⭐️ <b>Реферальная программа</b>\n\nЗа нового пользователя: <b>{0} ₽</b>\nС его пополнений: <b>{1}%</b>\nС его покупок: <b>{2}%</b>\nСкидка приглашённому: <b>{3}%</b>\nПриглашено: <b>{4}</b>\n\n<b>Твоя ссылка:</b>\n<code>{5}</code>\n\nПроценты начисляются от фактически оплаченной суммы, без бонусных зачислений. Награда за нового пользователя выдаётся один раз.", f"{settings['signup_bonus']:.2f}", f"{settings['deposit_pct']:.2f}", f"{settings['bonus_pct']:.2f}", f"{settings['discount_pct']:.2f}", count, ref_link)
    label_back, emoji_back = await _btn_text('btn_back_profile', tr('« Назад'), c.BTN_ICON_BACK_SMILE)
    from utils.button_icons import icon_for
    from database import referrals
    daily = (await referrals.summary(call.from_user.id))['daily']
    text += tr('\n\nЛимит в сутки по Москве: {0} ₽\nНачислено сегодня: {1} ₽\nОсталось: {2} ₽', daily['limit'], daily['issued'], daily['remaining'])
    if daily['blocked']:
        text += tr('\nРеферальные начисления заблокированы администратором.')
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('Мои рефералы'), callback_data='referral_users:0', icon_custom_emoji_id=icon_for('users'))], [InlineKeyboardButton(text=label_back, callback_data='my_profile', icon_custom_emoji_id=emoji_back)]])
    await edit_message_safe(call, text, reply_markup=kb)
    await answer_safe(call)


@profile_router.callback_query(F.data.startswith('referral_users:'))
async def invited_users(call: CallbackQuery):
    value = call.data.partition(':')[2]
    if not value.isascii() or not value.isdigit() or not 0 <= int(value) <= 10000:
        await answer_safe(call, tr('Некорректный параметр.'), show_alert=True)
        return
    from handlers.admin.referrals import render_invited
    await render_invited(call, call.from_user.id, int(value))
