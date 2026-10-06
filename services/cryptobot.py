import aiohttp
import logging
from aiogram import Router ,F 
from aiogram .fsm .context import FSMContext 
from aiogram .fsm .state import State ,StatesGroup 
from aiogram .types import CallbackQuery ,InlineKeyboardButton ,InlineKeyboardMarkup ,Message 

from config import CRYPTOBOT_TOKEN 
from database.db import add_balance, add_balance_usdt, is_comment_used, mark_comment_used, try_mark_comment_used, log_payment
from keyboards .user_kb import balance_menu 
from services.exchange import convert_to_ton
from utils .nav import edit_message_safe, answer_safe 

crypto_router =Router ()

class CryptoState (StatesGroup ):
    waiting_amount =State ()


FALLBACK_RUB_PER_USDT =100.0 
FALLBACK_RUB_PER_TON =200.0 



async def _post_api (method :str ,payload :dict =None )->dict |list |None :
    if payload is None :
        payload ={}
    url =f"https://pay.crypt.bot/api/{method }"
    headers ={"Crypto-Pay-API-Token":CRYPTOBOT_TOKEN }
    try :
        async with aiohttp .ClientSession ()as session :
            async with session .post (url ,headers =headers ,json =payload )as resp :
                if resp .status !=200 :
                    return None 
                body =await resp .json ()
                if not body .get ("ok"):
                    return None 
                return body .get ("result")
    except Exception :
        return None 

async def _get_api (method :str ,params :dict =None )->dict |list |None :
    if params is None :
        params ={}
    url =f"https://pay.crypt.bot/api/{method }"
    headers ={"Crypto-Pay-API-Token":CRYPTOBOT_TOKEN }
    try :
        async with aiohttp .ClientSession ()as session :
            async with session .get (url ,headers =headers ,params =params )as resp :
                if resp .status !=200 :
                    return None 
                body =await resp .json ()
                if not body .get ("ok"):
                    return None 
                return body .get ("result")
    except Exception :
        return None 



async def get_exchange_rates ()->list |None :
    return await _get_api ("getExchangeRates")

async def create_invoice (amount :float ,asset :str ="USDT")->dict |None :
    return await _post_api (
    "createInvoice",
    {"asset":asset ,"amount":str (amount ),"description":"Пополнение баланса"},
    )

async def get_invoices (params :dict =None )->list |None :
    res =await _get_api ("getInvoices",params )
    return res .get ("items")if res else None 

async def invoice_by_id (invoice_id :int )->dict |None :
    items =await get_invoices ({"invoice_ids":str (int (invoice_id ))})
    return items [0 ]if items else None 



async def get_current_rate (source :str ,target :str ="RUB")->float :
    rates = await get_exchange_rates ()
    if rates :
        for rate in rates :
            if rate .get ("source")==source and rate .get ("target")==target :
                val = float (rate .get ("rate",0 ))
                if val > 0:
                    return val

    if source =="USDT":return FALLBACK_RUB_PER_USDT 
    if source =="TON":return FALLBACK_RUB_PER_TON 
    return FALLBACK_RUB_PER_USDT 
@crypto_router.callback_query(F.data == "deposit_crypto")
async def deposit_crypto_entry(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(crypto_asset="USDT")
    await state.set_state(CryptoState.waiting_amount)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="topup_balance")],
        ]
    )

    text = (
        f"<tg-emoji emoji-id=\"5406841020769936275\">☺️</tg-emoji> <b>Пополнение в USDT через CryptoBot</b>\n\n"
        f"Введите сумму пополнения в <b>USDT ($)</b>:\n"
        f"<i>Пришлите число, например: </i><code>5</code><i> или </i><code>10</code>"
    )
    await edit_message_safe(call, text, reply_markup=kb)
    await answer_safe(call)


@crypto_router.message(CryptoState.waiting_amount, F.text)
async def crypto_process_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.strip().replace(",", "."))
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше нуля. Введите ещё раз:")
            return

        data = await state.get_data()
        asset = data.get("crypto_asset", "USDT")

        invoice = await create_invoice(amount, asset)
        if not invoice:
            await message.answer("❌ Ошибка API при создании счёта. Попробуйте позже.")
            return

        iid = invoice["invoice_id"]
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Оплатить",
                        url=invoice["pay_url"],
                        icon_custom_emoji_id="5258108352008823107"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Проверить оплату",
                        callback_data=f"cp:{iid}",
                        icon_custom_emoji_id="5258420634785947640"
                    )
                ],
                [InlineKeyboardButton(text="Назад", callback_data="deposit_crypto")],
            ]
        )

        await message.answer(
            f"<tg-emoji emoji-id='5467737386374947985'>✅</tg-emoji> <b>Счёт успешно создан!</b>\n\n"
            f"Сумма к оплате: <b>{amount} {asset}</b>\n\n"
            f"Оплатите по ссылке ниже 👇",
            reply_markup=kb
        )
        await state.clear()

    except ValueError:
        await message.answer("❌ Введите сумму числом, например: <code>5</code> или <code>2.5</code>")


@crypto_router .callback_query (F .data .startswith ("cp:"))
async def crypto_check_paid (call :CallbackQuery ):
    inv_id =int (call .data .split (":",1 )[1 ])
    comment_key = f"crypto_{inv_id}"

    # Быстрая проверка до запроса к API
    if await is_comment_used(comment_key):
        await answer_safe(call, "❌ Этот платёж уже был зачислен!",show_alert =True )
        return

    item =await invoice_by_id (inv_id )

    if not item:
        await answer_safe(call, "Счёт не найден.",show_alert =True )
        return 
    if item .get ("status")!="paid":
        await answer_safe(call, "⌛️ Оплата ещё не дошла.",show_alert =True )
        return 

    asset = str(item.get("asset", "USDT")).upper()
    amount = float(item.get("amount", 0) or 0)

    # Атомарная защита от дублирования через INSERT IGNORE + rowcount
    marked = await try_mark_comment_used(comment_key)
    if not marked:
        await answer_safe(call, "❌ Этот платёж уже был зачислен!", show_alert=True)
        return

    if asset == "USDT":
        await add_balance_usdt(call.from_user.id, amount)
        await log_payment(call.from_user.id, amount, "USDT", "cryptobot", comment_key)
        logging.info(f"[cryptobot] Payment credited: user={call.from_user.id}, amount={amount:.8f} USDT, invoice={inv_id}")
        
        await edit_message_safe (
            call ,
            f"<tg-emoji emoji-id='5427009714745517609'>✅</tg-emoji> <b>Оплата получена!</b>\n\n"
            f"Ваш баланс пополнен на <b>{amount :.2f} USDT</b>.",
            reply_markup =balance_menu (),
        )
    elif asset == "TON":
        await add_balance(call.from_user.id, amount)
        await log_payment(call.from_user.id, amount, "TON", "cryptobot", comment_key)
        logging.info(f"[cryptobot] Payment credited: user={call.from_user.id}, amount={amount:.8f} TON, invoice={inv_id}")
        
        await edit_message_safe (
            call ,
            f"<tg-emoji emoji-id='5427009714745517609'>✅</tg-emoji> <b>Оплата получена!</b>\n\n"
            f"Ваш баланс пополнен на <b>{amount :.4f} TON</b>.",
            reply_markup =balance_menu (),
        )
    else:
        ton_amount = await convert_to_ton(amount, asset)
        if ton_amount <= 0:
            ton_amount = amount # fallback

        await add_balance(call.from_user.id, ton_amount)
        await log_payment(call.from_user.id, ton_amount, "TON", "cryptobot", comment_key)
        logging.info(f"[cryptobot] Payment credited: user={call.from_user.id}, amount={ton_amount:.8f} TON, invoice={inv_id}")
        
        await edit_message_safe (
            call ,
            f"<tg-emoji emoji-id='5427009714745517609'>✅</tg-emoji> <b>Оплата получена!</b>\n\n"
            f"Ваш баланс пополнен на <b>{ton_amount :.4f} TON</b>.",
            reply_markup =balance_menu (),
        )

    await answer_safe(call, "Баланс пополнен!",show_alert =True )