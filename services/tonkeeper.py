import time
import logging
import aiohttp 

from aiogram import Router ,F 
from aiogram .fsm .context import FSMContext 
from aiogram .fsm .state import State ,StatesGroup 
from aiogram .types import CallbackQuery ,InlineKeyboardButton ,InlineKeyboardMarkup ,Message 

from config import TONKEEPER_WALLET 
from database.db import add_balance, add_deposit_with_first_bonus, is_comment_used, mark_comment_used, try_mark_comment_used, log_payment, get_setting
from keyboards .user_kb import balance_menu 
from utils .nav import edit_message_safe, answer_safe


from services .cryptobot import get_current_rate 

tonkeeper_router =Router ()

class TonState (StatesGroup ):
    waiting_amount =State ()



async def get_ton_transactions (wallet :str ,limit :int =15 )->list :
    url ="https://toncenter.com/api/v2/getTransactions"
    params ={"address":wallet ,"limit":limit }

    try :
        async with aiohttp .ClientSession ()as session :
            async with session .get (url ,params =params )as resp :
                if resp .status ==200 :
                    data =await resp .json ()
                    if data .get ("ok"):
                        return data .get ("result",[])
    except Exception :
        pass 
    return []

async def check_payment_by_comment(expected_comment: str) -> int:
    """Суммирует все транзакции с данным комментарием."""
    wallet = await get_setting("tonkeeper_wallet", TONKEEPER_WALLET)
    transactions = await get_ton_transactions(wallet)
    total_nano = 0
    for tx in transactions:
        in_msg = tx.get("in_msg", {})
        value_nano = int(in_msg.get("value", 0))
        if value_nano <= 0:
            continue
        message = in_msg.get("message", "")
        if message == expected_comment:
            total_nano += value_nano
    return total_nano




@tonkeeper_router .callback_query (F .data =="deposit_ton")
async def tonkeeper_screen (call :CallbackQuery ):
    kb =InlineKeyboardMarkup (
    inline_keyboard =[
    [
    InlineKeyboardButton (
    text ="Ввести свою сумму",
    callback_data ="tk_custom",
    icon_custom_emoji_id ="5258368777350816286"
    )
    ],
    [InlineKeyboardButton (text ="Назад",callback_data ="balance")],
    ]
    )

    text =(
    "<tg-emoji emoji-id='5451810389215954733'>💎</tg-emoji> <b>Пополнение через Tonkeeper</b>\n\n"
    "Выберите вариант пополнения:\n\n"
    "• <b>Автоматическое</b> — прямой перевод по реквизитам\n"
    "• <b>Своя сумма</b> — введите сумму в TON вручную"
    )

    await edit_message_safe (call ,text ,reply_markup =kb )
    await answer_safe (call )


@tonkeeper_router .callback_query (F .data =="tk_custom")
async def tonkeeper_custom_amount (call :CallbackQuery ,state :FSMContext ):
    ton_rate =await get_current_rate ("TON","RUB")

    kb =InlineKeyboardMarkup (
    inline_keyboard =[
    [InlineKeyboardButton (text ="Отмена",callback_data ="deposit_ton")],
    ]
    )
    await edit_message_safe (
    call ,
    f"<tg-emoji emoji-id='5312057711091813718'>💰</tg-emoji> <b>Введите сумму в TON</b>\n\n"
    f"Минимум: 0.05 TON\n"
    f"Курс: 1 TON ≈ {ton_rate :.2f}₽\n\n"
    f"<i>Пришлите сумму цифрами, например: 1.5</i>",
    reply_markup =kb 
    )
    await state .set_state (TonState .waiting_amount )
    await answer_safe (call )


@tonkeeper_router .message (TonState .waiting_amount ,F .text )
async def tonkeeper_process_amount (message :Message ,state :FSMContext ):
    try :
        ton_amount = float (message .text .strip ().replace(",", "."))
        if ton_amount < 0.05:
            await message .answer ("❌ Минимум 0.05 TON. Введите ещё раз:")
            return 

        ton_rate =await get_current_rate ("TON","RUB")
        rub_amount =round (ton_amount * ton_rate ,2 )


        comment =f"id{message .from_user .id }t{int (time .time ())}"
        nano_ton =int (ton_amount *1_000_000_000 )


        wallet = await get_setting("tonkeeper_wallet", TONKEEPER_WALLET)
        pay_url =f"ton://transfer/{wallet}?amount={nano_ton }&text={comment }"

        text =(
        "<tg-emoji emoji-id='5451810389215954733'>💎</tg-emoji> <b>Пополнение через Tonkeeper</b>\n\n"
        "<tg-emoji emoji-id='5467737386374947985'>✅</tg-emoji> <b>Заявка создана</b>\n\n"
        "<tg-emoji emoji-id='5312057711091813718'>💳</tg-emoji> <b>Кошелёк для перевода:</b>\n"
        f"<code>{wallet}</code>\n\n"
        f"<tg-emoji emoji-id='5406976471153545018'>💰</tg-emoji> <b>Сумма:</b> <code>{ton_amount } TON</code> (~{rub_amount }₽)\n\n"
        f"<tg-emoji emoji-id='5443038326535759644'>💬</tg-emoji> <b>Комментарий (ОБЯЗАТЕЛЬНО):</b>\n"
        f"<code>{comment }</code>\n\n"
        f"<tg-emoji emoji-id='5408830295002593386'>📤</tg-emoji> <b>Важно:</b>\n"
        f"• Переведите ровно указанную сумму\n"
        f"• Без комментария платеж <b>не зачислится</b>!\n"
        f"• После перевода нажмите кнопку ниже"
        )

        cb_data =f"tkc:{comment }|{nano_ton }"
        kb =InlineKeyboardMarkup (
        inline_keyboard =[
        [InlineKeyboardButton (text ="Оплатить в 1 клик",url =pay_url ,icon_custom_emoji_id ="5312057711091813718")],
        [
        InlineKeyboardButton (
        text ="Проверить оплату",
        callback_data =cb_data ,
        icon_custom_emoji_id ="5258420634785947640"
        )
        ],
        [InlineKeyboardButton (text ="Назад",callback_data ="deposit_ton")],
        ]
        )

        await message .answer (text ,reply_markup =kb )
        await state .clear ()

    except ValueError :
        await message .answer ("❌ Введите сумму цифрами.")


@tonkeeper_router .callback_query (F .data .startswith ("tkc:"))
async def tonkeeper_check_payment (call :CallbackQuery ):
    data_parts =call .data .replace ("tkc:","").split ("|")
    expected_comment =data_parts [0 ]
    expected_nano =int (data_parts [1 ])if len (data_parts )>1 else 0

    if await is_comment_used (expected_comment ):
        await answer_safe (call ,"❌ Этот платеж уже был зачислен!",show_alert =True )
        return 

    # Отвечаем сразу чтобы не получить timeout от Telegram
    await answer_safe (call ,"Проверяем блокчейн... 🔄")

    actual_nano = await check_payment_by_comment(expected_comment)
    if actual_nano > 0:
        if actual_nano < expected_nano:
            # Нельзя вызвать call.answer повторно — используем edit_message_safe
            await edit_message_safe(
                call,
                f"❌ <b>Получено меньше, чем требуется.</b>\n\n"
                f"Ожидалось: <code>{expected_nano / 1_000_000_000:.4f} TON</code>\n"
                f"Получено: <code>{actual_nano / 1_000_000_000:.4f} TON</code>\n\n"
                f"Отправьте недостающую сумму с тем же комментарием.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Проверить снова",
                                         callback_data=call.data,
                                         icon_custom_emoji_id="5258420634785947640")],
                    [InlineKeyboardButton(text="Назад", callback_data="deposit_ton")],
                ]),
            )
            return

        # Атомарная защита от дублирования через INSERT IGNORE + rowcount
        marked = await try_mark_comment_used(expected_comment)
        if not marked:
            await edit_message_safe(
                call,
                "❌ <b>Этот платеж уже был зачислен!</b>",
                reply_markup=balance_menu(),
            )
            return

        ton_amount = round(actual_nano / 1_000_000_000, 8)
        rub_amount = round(ton_amount * await get_current_rate("TON","RUB"), 2)
        await add_balance(call.from_user.id, rub_amount)
        await log_payment(call.from_user.id, rub_amount, "RUB", "tonkeeper", expected_comment)
        logging.info(f"[tonkeeper] Payment credited: user={call.from_user.id}, amount={ton_amount:.8f} TON, comment={expected_comment}")

        await edit_message_safe (
        call ,
        f"<tg-emoji emoji-id='5427009714745517609'>✅</tg-emoji> <b>Успешно!</b>\n\n"
        f"Ваш баланс пополнен на <b>{credited_amount:.2f} ₽</b>." + (f"\n🎁 Бонус за первое пополнение: <b>+{bonus_amount:.2f} ₽</b>." if bonus_amount > 0 else ""),
        reply_markup =balance_menu ()
        )
    else :
        await edit_message_safe(
            call,
            "⏳ <b>Транзакция не найдена.</b>\n\n"
            "Сеть TON обрабатывает перевод до 2 минут. Попробуйте ещё раз чуть позже.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Проверить снова", callback_data=call.data, icon_custom_emoji_id="5258420634785947640")],
                [InlineKeyboardButton(text="Назад", callback_data="deposit_ton")],
            ]),
        )