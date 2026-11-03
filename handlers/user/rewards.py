from datetime import datetime
from zoneinfo import ZoneInfo
from aiogram import Router,F
from aiogram.types import InlineKeyboardMarkup,InlineKeyboardButton
from database import rewards
from utils.nav import edit_message_safe,answer_safe
from utils.button_icons import icon_for

rewards_router=Router()


@rewards_router.callback_query(F.data.in_({'wheel','wheel_claim'}))
async def wheel(call):
    prize=None
    if call.data=='wheel_claim':
        try: prize=await rewards.claim(call.from_user.id)
        except ValueError as exc:
            await answer_safe(call,str(exc),show_alert=True);return
    status=await rewards.status(call.from_user.id)
    text='<b>Колесо удачи</b>\n\nПолучите случайно от 1 до 10 ₽ на баланс. Каждая целая сумма имеет одинаковый шанс — 10%.\n\nУсловия: подтверждённые пополнения в сумме от 50 ₽ за последние 72 часа. Крутить можно раз в 3 дня. Промокоды, подарки и возвращённые Stars не учитываются.\n\n'
    if prize: text+=f"Выпало <b>{prize['amount']} ₽</b>! Бонус уже зачислен.\n\n"
    text+=f"Подходящие пополнения: {status['paid']} ₽."
    if status['next_at']:
        next_at=datetime.fromisoformat(status['next_at']).astimezone(ZoneInfo('Europe/Moscow'))
        text+=f'\nИнтервал следующего получения: {next_at:%d.%m.%Y %H:%M} МСК.'
    rows=[]
    if status['eligible']: rows.append([InlineKeyboardButton(text='Крутить колесо',callback_data='wheel_claim',icon_custom_emoji_id=icon_for('reviews'))])
    else: rows.append([InlineKeyboardButton(text='Пополнить баланс',callback_data='topup_balance',icon_custom_emoji_id=icon_for('money'))])
    rows.append([InlineKeyboardButton(text='Мой профиль',callback_data='my_profile',icon_custom_emoji_id=icon_for('back'))])
    await edit_message_safe(call,text,reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)
