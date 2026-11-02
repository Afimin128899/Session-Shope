from aiogram import Router ,F 
from aiogram .filters import Command 
from aiogram .types import CallbackQuery ,Message 
from aiogram .fsm .context import FSMContext 
from aiogram .fsm .state import State ,StatesGroup 

from database.admin_tools import remove_account
from config import ADMIN_IDS 
from database .db import (
    add_account ,
    get_all_users ,
    create_promo ,
    update_country_price ,
    get_accounts_by_country ,
)
from utils .nav import edit_message_safe, answer_safe 
from keyboards .admin_kb import (
    back_to_admin ,
    get_admin_panel ,
    promos_menu ,
    prices_menu ,
    accounts_list_menu 
)

manage_router =Router ()

class ManageState (StatesGroup ):

    add_regular =State ()

    add_balance_user =State ()
    add_balance_amount =State ()
    set_balance_user =State ()
    set_balance_value =State ()
    create_promo =State ()
    edit_price_country =State ()
    edit_price_value =State ()

def is_admin (user_id :int )->bool :
    return user_id in ADMIN_IDS 


@manage_router .message (Command ("cancel"))
@manage_router .message (F .text =="/cancel")
async def cancel_manage_action (message :Message ,state :FSMContext ):
    if not is_admin (message .from_user .id ):return 
    await state .clear ()
    await message .answer ("❌ Действие отменено.",reply_markup =get_admin_panel ())


@manage_router .callback_query (F .data =="admin_add_account")
async def start_add_regular (call :CallbackQuery ,state :FSMContext ):
    if not is_admin (call .from_user .id ):return 
    await state .set_state (ManageState .add_regular )
    await edit_message_safe (
    call ,
    "📱 <b>Добавление ОБЫЧНОГО аккаунта</b>\n\n"
    "Введите данные одной строкой:\n"
    "<code>Страна|Код|Номер|Цена|Данные</code>\n\n"
    "Пример: <code>Россия|+7|79991234567|190|STRING_SESSION</code>",
    reply_markup =back_to_admin (),
    )
    await answer_safe(call)

@manage_router .message (ManageState .add_regular ,F .text )
async def process_add_regular (message :Message ,state :FSMContext ):
    if not is_admin (message .from_user .id ):return 
    try :
        parts =[p .strip ()for p in message .text .split ("|")]
        if len (parts )<5 :raise ValueError 
 
        country ,code ,number ,price ,data =parts [0 ],parts [1 ],parts [2 ],float (parts [3 ]),parts [4 ]
        await add_account (country ,code ,number ,price ,data )

        await state .clear ()
        await message .answer (f"✅ Аккаунт {number } (Обычный) добавлен!",reply_markup =get_admin_panel ())
    except Exception :
        await message .answer ("❌ Ошибка формата. Проверьте разделители | и число цены.",reply_markup =back_to_admin ())


@manage_router .callback_query (F .data =="admin_del_account")
async def start_del_account (call :CallbackQuery ):
    if not is_admin (call .from_user .id ):return 
    all_accounts =await get_accounts_by_country ("all")
    if not all_accounts :
        await edit_message_safe (call ,"🗑 В базе нет аккаунтов.",reply_markup =back_to_admin ())
        return 

    text =f"🗑 <b>Удаление</b>\nВсего: {len (all_accounts )}\nВыберите аккаунт:"
    await edit_message_safe (call ,text ,reply_markup =accounts_list_menu (all_accounts ,0 ))
    await answer_safe(call)

@manage_router .callback_query (F .data .startswith ("admin_delete_account_confirm:"))
async def confirm_delete_account (call :CallbackQuery ):
    if not is_admin (call .from_user .id ):return 
    account_id =int (call .data .split (":")[1 ])
    try:
        removed = await remove_account(call.from_user.id, account_id)
    except ValueError as exc:
        await answer_safe(call, str(exc), show_alert=True)
        return
    if not removed:
        await answer_safe(call, "Аккаунт уже удалён.", show_alert=True)
        return
    await edit_message_safe (call ,f"✅ Аккаунт #{account_id } удален.",reply_markup =back_to_admin ())
    await answer_safe(call)


@manage_router .callback_query (F .data =="admin_create_promo")
async def start_promo (call :CallbackQuery ,state :FSMContext ):
    if not is_admin (call .from_user .id ):return 
    await state .set_state (ManageState .create_promo )
    await edit_message_safe (call ,"🎟 Формат: <code>КОД|сумма|лимит</code>",reply_markup =back_to_admin ())

@manage_router .message (ManageState .create_promo ,F .text )
async def process_promo (message :Message ,state :FSMContext ):
    try :
        parts =message .text .split ("|")
        await create_promo (parts [0 ].upper (),float (parts [1 ]),int (parts [2 ]))
        await state .clear ()
        await message .answer ("✅ Промокод создан.",reply_markup =get_admin_panel ())
    except Exception :await message .answer ("Ошибка формата.")