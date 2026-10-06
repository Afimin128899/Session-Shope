"""
Модуль для работы с диалогом 777000 (сервисные коды Telegram).
Использует Telethon для чтения сообщений и поиска кодов подтверждения.
"""

import asyncio
import re
import logging
from datetime import datetime, timezone
from typing import Optional, Callable
from services.telethon_factory import create_client

# Настраиваем именованный логгер для модуля
logger = logging.getLogger("telethon_code")


def _validate_session(session_str: str) -> Optional[str]:
    """Проверяет валидность строки сессии и возвращает очищенную строку."""
    if not session_str or not isinstance(session_str, str):
        logger.warning("[_validate_session] Сессия пуста или не является строкой.")
        return None
    session_str = session_str.strip()
    if len(session_str) < 100:
        logger.warning(f"[_validate_session] Сессия слишком короткая ({len(session_str)} символов).")
        return None
    return session_str


def _extract_code(text: str) -> Optional[str]:
    """Извлекает 5-6 значный код из текста сообщения."""
    if not text:
        return None
    codes = re.findall(r'\b\d{5,6}\b', text)
    if codes:
        logger.info(f"[_extract_code] Извлечен код: {codes[0]} из текста: {text[:60]}...")
        return codes[0]
    return None


async def wait_for_code_from_777000(
    session_str: str,
    timeout: int = 120,
    interval: float = 2.0,
    last_msg_id: int = 0,
    after_time: Optional[datetime] = None
) -> Optional[str]:
    session_str = _validate_session(session_str)
    if not session_str:
        logger.error("[wait_for_code] Невалидная сессия (слишком короткая или не строка)")
        return None
    
    client = None
    try:
        try:
            logger.info("[wait_for_code] Инициализируем StringSession...")
            client = create_client(session_str=session_str)
        except Exception as e:
            logger.exception(
                f"[wait_for_code] КРИТИЧЕСКАЯ ОШИБКА: Не удалось инициализировать StringSession! "
                f"Длина сессии: {len(session_str)}. Детали: {e}"
            )
            return None
        
        logger.info("[wait_for_code] Подключаемся к сессии Telegram...")
        await asyncio.wait_for(client.connect(), timeout=10.0)
        logger.info("[wait_for_code] Подключение установлено, проверяем авторизацию...")
        
        is_auth = await asyncio.wait_for(client.is_user_authorized(), timeout=10.0)
        if not is_auth:
            logger.warning("[wait_for_code] Сессия НЕ авторизована в Telegram.")
            return None
        logger.info("[wait_for_code] Сессия успешно авторизована.")
        
        # Нормализуем after_time к UTC aware для корректного сравнения
        check_after: Optional[datetime] = None
        if after_time:
            if after_time.tzinfo is None:
                check_after = after_time.replace(tzinfo=timezone.utc)
            else:
                check_after = after_time
            logger.info(f"[wait_for_code] Ищем коды новее, чем {check_after}")

        logger.info("[wait_for_code] Получаем сущность 777000 (Telegram)...")
        entity_777000 = await client.get_entity(777000)
        
        logger.info("[wait_for_code] Получаем последние 20 сообщений от 777000...")
        messages = await client.get_messages(entity_777000, limit=20)
        logger.info(f"[wait_for_code] Найдено {len(messages)} сообщений в истории.")
        
        # Ищем подходящий код в истории (только новее after_time)
        found_code = None
        for msg in messages:
            if not msg.text:
                continue
            code = _extract_code(msg.text)
            if not code:
                continue

            msg_date = msg.date
            if msg_date and msg_date.tzinfo is None:
                msg_date = msg_date.replace(tzinfo=timezone.utc)

            if check_after and msg_date and msg_date <= check_after:
                logger.info(f"[wait_for_code] Пропускаем СТАРЫЙ код: {code} от {msg_date} (до {check_after})")
                continue

            logger.info(f"[wait_for_code] Найден подходящий код в истории: {code} от {msg_date}")
            found_code = code
            break  # берём самый свежий подходящий

        if found_code:
            return found_code
        
        # Кода в истории нет — ждём новый
        last_seen_msg_id = messages[0].id if messages else 0
        start_time = datetime.now()
        checks = 0
        
        logger.info(
            f"[wait_for_code] В истории нет валидного кода. Ожидаем новые сообщения... "
            f"timeout={timeout}s, min_id={last_seen_msg_id}"
        )
        
        while (datetime.now() - start_time).total_seconds() < timeout:
            checks += 1
            logger.info(f"[wait_for_code] Проверка #{checks} (прошло {(datetime.now() - start_time).total_seconds():.1f}s)...")
            
            latest_msgs = await client.get_messages(entity_777000, limit=5, min_id=last_seen_msg_id)
            
            for msg in latest_msgs:
                if not msg.text:
                    continue
                if msg.id <= last_seen_msg_id:
                    continue
                last_seen_msg_id = max(last_seen_msg_id, msg.id)
                logger.info(f"[wait_for_code] Получено новое сообщение: {msg.text[:100]}")
                
                code = _extract_code(msg.text)
                if code:
                    logger.info(f"[wait_for_code] УСПЕХ! Найден новый код: {code}")
                    return code
            
            await asyncio.sleep(interval)
        
        logger.warning(f"[wait_for_code] Превышен таймаут ожидания ({timeout}s). Проверено {checks} раз.")
        return None
        
    except Exception as e:
        logger.exception(f"[wait_for_code] Ошибка при чтении кода: {e}")
        return None
    finally:
        if client:
            try:
                logger.info("[wait_for_code] Отключаем сессию Telethon...")
                await client.disconnect()
                logger.info("[wait_for_code] Сессия успешно отключена.")
            except Exception as e:
                logger.error(f"[wait_for_code] Ошибка при отключении сессии: {e}")



async def get_last_valid_code(
    session_str: str,
    max_age_minutes: int = 5
) -> Optional[str]:
    """
    Получает последний валидный код из диалога 777000.
    """
    if not _validate_session(session_str):
        logger.warning("[get_last_valid_code] Невалидная сессия.")
        return None
    
    client = None
    try:
        logger.info("[get_last_valid_code] Инициализация клиента...")
        client = create_client(session_str=session_str)
        await asyncio.wait_for(client.connect(), timeout=10.0)
        
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10.0):
            logger.warning("[get_last_valid_code] Клиент не авторизован.")
            return None
        
        logger.info("[get_last_valid_code] Получение сообщений 777000...")
        entity_777000 = await client.get_entity(777000)
        messages = await client.get_messages(entity_777000, limit=20)
        
        current_time = datetime.now().timestamp()
        age_threshold = current_time - (max_age_minutes * 60)
        logger.info(f"[get_last_valid_code] Порог возраста сообщений: {max_age_minutes} мин.")
        
        valid_codes = []
        
        for msg in messages:
            msg_time = msg.date.timestamp() if msg.date else 0
            
            if msg_time >= age_threshold and msg.text:
                code = _extract_code(msg.text)
                if code:
                    valid_codes.append({
                        'code': code,
                        'timestamp': msg_time,
                        'date': msg.date,
                    })
        
        if valid_codes:
            valid_codes.sort(key=lambda x: x['timestamp'], reverse=True)
            logger.info(f"[get_last_valid_code] Найден последний валидный код: {valid_codes[0]['code']}")
            return valid_codes[0]['code']
        
        logger.info("[get_last_valid_code] Валидных кодов за последнее время не найдено.")
        return None
        
    except Exception as e:
        logger.exception(f"[get_last_valid_code] Ошибка: {e}")
        return None
    finally:
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass


async def confirm_action_with_code(
    session_str: str,
    action_callback: Optional[Callable] = None,
    timeout: int = 120,
    interval: float = 2.0
) -> tuple[bool, Optional[str], Optional[int]]:
    """
    Подтверждает действие через код от 777000.
    """
    if not _validate_session(session_str):
        logger.warning("[confirm_action] Невалидная сессия.")
        return False, None, 0
    
    client = None
    try:
        logger.info("[confirm_action] Инициализация клиента...")
        client = create_client(session_str=session_str)
        await asyncio.wait_for(client.connect(), timeout=10.0)
        
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10.0):
            logger.warning("[confirm_action] Клиент не авторизован.")
            return False, None, 0
        
        logger.info("[confirm_action] Получение последнего сообщения перед действием...")
        entity_777000 = await client.get_entity(777000)
        last_messages = await client.get_messages(entity_777000, limit=1)
        last_msg_id = last_messages[0].id if last_messages else 0
        
        if action_callback:
            logger.info("[confirm_action] Выполняем коллбэк действия (action_callback)...")
            await action_callback(client)
        
        start_time = datetime.now()
        logger.info(f"[confirm_action] Ожидание кода подтверждения (timeout={timeout}s)...")
        
        while (datetime.now() - start_time).total_seconds() < timeout:
            messages = await client.get_messages(entity_777000, limit=10, min_id=last_msg_id)
            
            for msg in messages:
                if msg.text:
                    code = _extract_code(msg.text)
                    if code:
                        logger.info(f"[confirm_action] Код получен: {code}")
                        return True, code, msg.id
            
            await asyncio.sleep(interval)
        
        logger.warning("[confirm_action] Время ожидания кода истекло.")
        return False, None, last_msg_id
        
    except Exception as e:
        logger.exception(f"[confirm_action] Ошибка: {e}")
        return False, None, 0
    finally:
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass


async def get_777000_dialog_info(session_str: str) -> Optional[dict]:
    """Получает информацию о диалоге с 777000."""
    if not _validate_session(session_str):
        return None
    
    client = None
    try:
        logger.info("[get_777000_dialog_info] Инициализация клиента...")
        client = create_client(session_str=session_str)
        await asyncio.wait_for(client.connect(), timeout=10.0)
        
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10.0):
            return None
        
        logger.info("[get_777000_dialog_info] Запрос сущности и сообщений...")
        entity = await client.get_entity(777000)
        messages = await client.get_messages(entity, limit=5)
        
        return {
            'entity': entity,
            'messages_count': len(messages),
            'last_message': messages[0].text[:100] if messages and messages[0].text else None,
            'last_message_time': messages[0].date if messages else None,
        }
        
    except Exception as e:
        logger.exception(f"[get_777000_dialog_info] Ошибка: {e}")
        return None
    finally:
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass


async def poll_for_code(
    session_str: str,
    phone: str = None,
    after_time=None,
    interval: float = 2.0,
    max_wait: float = 60.0
) -> Optional[str]:
    """
    Получает код из диалога 777000.
    """
    if not _validate_session(session_str):
        logger.warning("[poll_for_code] Невалидная сессия.")
        return None
    
    parse_after = None
    if after_time:
        if isinstance(after_time, str):
            try:
                parse_after = datetime.strptime(after_time, "%Y-%m-%d %H:%M:%S")
            except Exception:
                parse_after = None
        elif isinstance(after_time, datetime):
            parse_after = after_time
        logger.info(f"[poll_for_code] after_time распарсен как: {parse_after}")
    
    client = None
    try:
        logger.info("[poll_for_code] Инициализация клиента...")
        client = create_client(session_str=session_str)
        logger.info("[poll_for_code] Подключение к Telegram...")
        await asyncio.wait_for(client.connect(), timeout=10.0)
        
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10.0):
            logger.warning("[poll_for_code] Пользователь НЕ авторизован в этой сессии. Возможно, сессия устарела или неактивна.")
            return "SESSION_NOT_AUTHORIZED"
        
        logger.info("[poll_for_code] Авторизация подтверждена. Получение сущности 777000...")
        entity_777000 = await client.get_entity(777000)
        
        logger.info("[poll_for_code] Шаг 1: Проверяем последние 10 сообщений в истории диалога на наличие свежего кода...")
        recent_messages = await client.get_messages(entity_777000, limit=10)
        
        for msg in recent_messages:
            if msg.text:
                code = _extract_code(msg.text)
                if code:
                    msg_date = msg.date
                    if msg_date:
                        now_utc = datetime.now(timezone.utc)
                        msg_date_utc = msg_date if msg_date.tzinfo else msg_date.replace(tzinfo=timezone.utc)
                        age_seconds = (now_utc - msg_date_utc).total_seconds()
                        
                        # Если задан parse_after, проверяем по дате
                        if parse_after:
                            parse_after_utc = parse_after if parse_after.tzinfo else parse_after.replace(tzinfo=timezone.utc)
                            if msg_date_utc <= parse_after_utc:
                                logger.info(f"[poll_for_code] Найден старый код {code} (дата {msg_date_utc} <= {parse_after_utc}), пропускаем.")
                                continue
                        
                        # Код валиден, если получен за последние 15 минут (900 секунд)
                        if age_seconds < 900:
                            logger.info(f"[poll_for_code] УСПЕХ! Найден свежий код в истории: {code} (возраст: {age_seconds:.1f}s, дата: {msg_date_utc})")
                            return code
                        else:
                            logger.info(f"[poll_for_code] Найден старый код {code} в истории (возраст: {age_seconds:.1f}s, дата: {msg_date_utc}), пропускаем.")
                    else:
                        logger.info(f"[poll_for_code] УСПЕХ! Найден код в истории без даты: {code}")
                        return code

        # Запоминаем ID самого свежего сообщения перед переходом к ожиданиям
        last_msg_id = recent_messages[0].id if recent_messages else 0
        logger.info(f"[poll_for_code] Шаг 2: Свежего кода в истории не найдено. Начинаем цикл ожидания нового кода. Начальный ID: {last_msg_id}")
        
        start_time = datetime.now()
        checks = 0
        while (datetime.now() - start_time).total_seconds() < max_wait:
            checks += 1
            logger.info(f"[poll_for_code] Попытка #{checks} (прошло {(datetime.now() - start_time).total_seconds():.1f}s)...")
            messages = await client.get_messages(entity_777000, limit=10, min_id=last_msg_id)
            
            for msg in messages:
                if msg.text:
                    code = _extract_code(msg.text)
                    if code:
                        logger.info(f"[poll_for_code] УСПЕХ! Получен новый код из входящего сообщения: {code}")
                        return code
            
            await asyncio.sleep(interval)
        
        logger.warning(f"[poll_for_code] Шаг 3: Цикл ожидания завершен. Код не получен за {max_wait}s.")
        return None
        
    except Exception as e:
        logger.exception(f"[poll_for_code] Ошибка в процессе получения кода: {e}")
        return None
    finally:
        if client:
            try:
                logger.info("[poll_for_code] Отключение сессии Telethon...")
                await client.disconnect()
                logger.info("[poll_for_code] Сессия успешно отключена.")
            except Exception as e:
                logger.error(f"[poll_for_code] Ошибка при отключении сессии: {e}")


async def poll_for_new_code(
    session_str: str,
    phone: str = None,
    after_time=None,
    interval: float = 2.0,
    max_wait: float = 30.0
) -> Optional[str]:
    """Обёртка для poll_for_code с настройками для нового кода."""
    logger.info(f"[poll_for_new_code] Вызов обертки. phone={phone}, max_wait={max_wait}s")
    return await poll_for_code(str(session_str), phone, after_time=after_time, interval=interval, max_wait=max_wait)


async def try_fetch_login_code(session_str: str, phone: str = None) -> Optional[str]:
    """Быстрая проверка кода без долгого ожидания."""
    logger.info(f"[try_fetch_login_code] Вызов быстрой проверки. phone={phone}")
    return await poll_for_code(str(session_str), phone, interval=2.0, max_wait=10.0)
