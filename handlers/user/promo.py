from aiogram import Router ,F 
from aiogram .fsm .context import FSMContext 
from aiogram .fsm .state import State ,StatesGroup 
from aiogram .types import CallbackQuery ,Message ,InlineKeyboardMarkup ,InlineKeyboardButton 

from database .db import check_and_use_promo ,create_user 
from keyboards .user_kb import promo_cancel 
from utils .nav import edit_main ,ensure_user ,edit_message_safe, answer_safe 

promo_router =Router ()


class PromoState (StatesGroup ):
    waiting_for_promo =State ()


@promo_router .callback_query (F .data =="promo")
async def ask_promo (call :CallbackQuery ,state :FSMContext ):
    await ensure_user (call .from_user .id )
    await edit_message_safe (call ,"<tg-emoji emoji-id=\"5226513232549664618\">🔢</tg-emoji> <b>Ввод промокода</b>\n\nВведите ваш промокод ниже:",reply_markup =promo_cancel ())
    await state .set_state (PromoState .waiting_for_promo )
    await answer_safe(call)


@promo_router .callback_query (F .data =="promo_cancel")
async def cancel_promo (call :CallbackQuery ,state :FSMContext ):
    await state .clear ()
    await edit_main (call )
    await answer_safe(call)


@promo_router .message (PromoState .waiting_for_promo ,F .text )
async def process_promo (message :Message ,state :FSMContext ):
    await create_user (message .from_user .id )


    code =message .text .strip ().upper ()


    value =await check_and_use_promo (message .from_user .id ,code )
    await state .clear ()


    kb =InlineKeyboardMarkup (
    inline_keyboard =[
    [InlineKeyboardButton (text ="« В главное меню",callback_data ="main_menu")]
    ]
    )

    if value > 0:
        await message.answer(
            f"✅ <b>Промокод активирован!</b>\n\n"
            f"На ваш баланс зачислено: <b>{value:.2f}</b> 💸",
            reply_markup=kb,
        )
    else :

        await message .answer (
        "❌ <b>Ошибка активации.</b>\n\n"
        "Возможные причины:\n"
        "• Промокод введен неверно\n"
        "• Исчерпан общий лимит активаций\n"
        "• Вы уже использовали этот промокод ранее",
        reply_markup =kb 
        )