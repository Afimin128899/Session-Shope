from __future__ import annotations 

import logging 
from typing import Optional ,Tuple ,Dict 
from telethon import TelegramClient 
from telethon .sessions import StringSession 
from telethon .errors import (
SessionPasswordNeededError ,
PhoneCodeInvalidError ,
PhoneNumberInvalidError ,
PasswordHashInvalidError 
)
from config import TELEGRAM_API_ID ,TELEGRAM_API_HASH 


logger =logging .getLogger (__name__ )


_active_clients :Dict [int ,TelegramClient ]={}

_COUNTRY_PREFIXES =[
("+7","Россия"),
("+1","США"),
("+380","Украина"),
("+91","Индия"),
("+44","Великобритания"),
("+880","Бангладеш"),
("+34","Испания"),
]

def _detect_country_by_phone (phone :str )->str :
    phone =phone .replace (" ","").replace ("-","").replace ("(","").replace (")","").lstrip ("+")
    for prefix ,country in sorted (_COUNTRY_PREFIXES ,key =lambda x :len (x [0 ]),reverse =True ):
        clean_prefix =prefix .lstrip ("+")
        if phone .startswith (clean_prefix ):
            return country 
    return "Неизвестно"

async def import_session_file(session_path: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Проверить SQLite .session и экспортировать её в StringSession."""
    client = None
    try:
        if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
            return None, None, "API_ID/HASH не найдены в конфиге"

        client = TelegramClient(
            session_path,
            int(TELEGRAM_API_ID),
            TELEGRAM_API_HASH,
            device_model="PC 64bit",
            system_version="Windows 10",
            app_version="4.16.8 x64",
            lang_code="ru",
            system_lang_code="ru-RU",
        )
        await client.connect()

        if not await client.is_user_authorized():
            return None, None, "Сессия не авторизована в Telegram"

        me = await client.get_me()
        if not me or not me.phone:
            return None, None, "Не удалось получить номер телефона из сессии"

        phone = f"+{me.phone}"
        # Telethon поддерживает экспорт любой Session в StringSession.
        session_string = StringSession.save(client.session)
        if not session_string:
            return None, None, "Не удалось экспортировать сессию"

        return session_string, phone, None
    except Exception as e:
        logger.exception("Ошибка импорта .session файла: %s", e)
        return None, None, str(e)
    finally:
        if client:
            try:
                await client.disconnect()
            except Exception:
                logger.exception("Ошибка отключения импортируемой сессии")


async def create_telethon_client() -> TelegramClient:
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        raise ValueError("API_ID/HASH не найдены в конфиге")

    client = TelegramClient(
        StringSession(),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
        device_model="PC 64bit",
        system_version="Windows 10",
        app_version="4.16.8 x64",
        lang_code="ru",
        system_lang_code="ru-RU",
    )
    await client.connect()
    return client 

async def send_code_to_phone (client :TelegramClient ,phone :str )->Tuple [Optional [str ],Optional [str ]]:
    try :
        result =await client .send_code_request (phone )
        return result .phone_code_hash ,None 
    except Exception as e :
        logger .error (f"Ошибка отправки кода на {phone }: {e }")
        err_msg = str (e )
        err_msg_lower = err_msg .lower ()
        if "banned" in err_msg_lower or "phone_number_banned" in err_msg_lower:
            err_text = "Этот номер телефона заблокирован в Telegram."
        elif "flood" in err_msg_lower:
            err_text = "Слишком много попыток отправки. Попробуйте другой номер или подождите некоторое время."
        elif "invalid" in err_msg_lower or "phone_number_invalid" in err_msg_lower:
            err_text = "Неверный формат или несуществующий номер телефона."
        else :
            err_text = err_msg 
        return None ,err_text 

async def verify_login_code (client :TelegramClient ,phone :str ,code :str ,phone_code_hash :str )->Tuple [bool ,Optional [str ],bool ]:
    try :
        await client .sign_in (phone =phone ,code =code ,phone_code_hash =phone_code_hash )
        return True ,None ,False 
    except PhoneCodeInvalidError :
        return False ,"Неверный код подтверждения.",False 
    except SessionPasswordNeededError :
        return False ,None ,True 
    except Exception as e :
        return False ,f"Ошибка: {str (e )}",False 

async def verify_2fa_password (client :TelegramClient ,password :str )->Tuple [bool ,Optional [str ]]:
    try :
        await client .sign_in (password =password )
        return True ,None 
    except PasswordHashInvalidError :
        return False ,"Неверный пароль 2FA."
    except Exception as e :
        return False ,f"Ошибка 2FA: {str (e )}"

async def finalize_account (client :TelegramClient )->Tuple [Optional [str ],Optional [str ],Optional [str ]]:
    """Возвращает (session_string, phone, country)"""
    try :
        me =await client .get_me ()
        if not me :
            return None ,None ,"Не удалось получить данные профиля"

        phone =f"+{me .phone }"
        country =_detect_country_by_phone (phone )
        session_string =client .session .save ()


        await client .disconnect ()
        return session_string ,phone ,country 
    except Exception as e :
        await client .disconnect ()
        return None ,None ,str (e )


def cache_client (user_id :int ,client :TelegramClient ):
    _active_clients [user_id ]=client 

def get_cached_client (user_id :int )->Optional [TelegramClient ]:
    return _active_clients .get (user_id )

async def remove_cached_client (user_id :int ):
    client =_active_clients .pop (user_id ,None )
    if client :
        await client .disconnect ()

async def cleanup_all_clients ():
    for user_id in list (_active_clients .keys ()):
        await remove_cached_client (user_id )