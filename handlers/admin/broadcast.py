import asyncio 
from datetime import datetime 

from aiogram import Bot ,Router ,F 
from aiogram .fsm .context import FSMContext 
from aiogram .fsm .state import State ,StatesGroup 
from aiogram .types import CallbackQuery ,InlineKeyboardButton ,InlineKeyboardMarkup ,Message 

from config import ADMIN_IDS 
from database .db import get_all_users ,log_broadcast 
from utils .nav import edit_message_safe, answer_safe 

broadcast_router =Router ()


class BroadcastState (StatesGroup ):
    waiting_content =State ()
    waiting_button =State ()


def is_admin (user_id :int )->bool :
    return user_id in ADMIN_IDS 


@broadcast_router .callback_query (F .data =="admin_broadcast")
async def broadcast_start (call :CallbackQuery ,state :FSMContext ):
    if not is_admin (call .from_user .id ):
        await answer_safe(call)
        return 
    await state .set_state (BroadcastState .waiting_content )
    kb =InlineKeyboardMarkup (
    inline_keyboard =[
    [InlineKeyboardButton (text ="« Отмена",callback_data ="admin_home")],
    ]
    )
    await edit_message_safe (
    call ,
    "Отправьте <b>текст</b> или <b>фото</b> (с подписью). Затем зададим кнопку (или пропустим).",
    reply_markup =kb ,
    )
    await answer_safe(call)


def _markup_from_spec (spec :str )->InlineKeyboardMarkup |None :
    spec =spec .strip ()
    if not spec or spec =="-":
        return None 
    if "|"not in spec :
        return None 
    label ,_ ,url =spec .partition ("|")
    label ,url =label .strip (),url .strip ()
    if not label or not url .startswith ("http"):
        return None 
    return InlineKeyboardMarkup (inline_keyboard =[[InlineKeyboardButton (text =label ,url =url )]])


@broadcast_router .message (BroadcastState .waiting_content )
async def broadcast_got_content (message :Message ,state :FSMContext ):
    if not is_admin (message .from_user .id ):
        return 
    if not message .text and not message .caption and not message .photo :
        await message .answer ("Нужен текст или фото.")
        return 
    await state .update_data (
    bc_source_chat =message .chat .id ,
    bc_source_msg =message .message_id ,
    )
    await state .set_state (BroadcastState .waiting_button )
    await message .answer (
    "Кнопка: <code>Подпись|https://ссылка</code>\nИли <code>-</code> без кнопки."
    )


@broadcast_router .message (BroadcastState .waiting_button ,F .text )
async def broadcast_run (message :Message ,state :FSMContext ,bot :Bot ):
    if not is_admin (message .from_user .id ):
        return 
    data =await state .get_data ()
    await state .clear ()
    chat_id =data .get ("bc_source_chat")
    msg_id =data .get ("bc_source_msg")
    markup =_markup_from_spec (message .text )

    users =await get_all_users ()
    ok ,fail =0 ,0 

    for u in users :
        uid =int (u ["id"])
        try :
            await bot .copy_message (
            chat_id =uid ,
            from_chat_id =chat_id ,
            message_id =msg_id ,
            reply_markup =markup ,
            )
            ok +=1 
            await asyncio .sleep (0.035 )
        except Exception :
            fail +=1 

    note =(message .text or "")[:200 ]
    await log_broadcast (
    message .from_user .id ,
    datetime .now ().strftime ("%Y-%m-%d %H:%M:%S"),
    len (users ),
    ok ,
    fail ,
    note ,
    )
    await message .answer (
    f"Рассылка завершена.\nУспешно: {ok }\nОшибок: {fail }\nЖурнал в broadcast_logs.",
    reply_markup =InlineKeyboardMarkup (
    inline_keyboard =[[InlineKeyboardButton (text ="« В панель",callback_data ="admin_home")]]
    ),
    )
