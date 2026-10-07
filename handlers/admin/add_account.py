from aiogram import Router ,F 
from aiogram .fsm .context import FSMContext 
from aiogram .fsm .state import State ,StatesGroup 
from aiogram .types import CallbackQuery ,Message ,InlineKeyboardButton ,InlineKeyboardMarkup 
from aiogram .filters import StateFilter ,Command 

from services .telethon_auth import (
create_telethon_client ,
send_code_to_phone ,
verify_login_code ,
verify_2fa_password ,
finalize_account ,
cache_client ,
get_cached_client ,
remove_cached_client ,
)
from database .db import add_account, get_all_categories
from keyboards .admin_kb import back_to_admin 
from utils .nav import edit_message_safe, answer_safe 
from utils.country_codes import detect_country, detect_country_code, detect_country_flag
from utils.emoji_map import EMOJI_PHONE, EMOJI_MEGA, EMOJI_LOCK, EMOJI_CHECK

from config import ADMIN_IDS

add_account_router = Router()


class AddAccountState(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_2fa = State()
    waiting_for_session_file = State()
    waiting_for_price = State()
    waiting_for_category = State()


@add_account_router.message(Command("cancel"))
@add_account_router.message(F.text == "/cancel")
async def cancel_add_account(message: Message, state: FSMContext):
    """Отменить процесс добавления аккаунта."""
    await state.clear()
    await remove_cached_client(message.from_user.id)
    await message.answer("❌ Процесс добавления аккаунта отменён.", reply_markup=back_to_admin())


@add_account_router.callback_query(F.data == "add_account_session")
async def start_add_account_session(call: CallbackQuery, state: FSMContext):
    """Начать добавление уже авторизованного Telegram .session файла."""
    if call.from_user.id not in ADMIN_IDS:
        await answer_safe(call, "❌ У вас нет прав админа.", show_alert=True)
        return

    await state.clear()
    await state.set_state(AddAccountState.waiting_for_session_file)
    await edit_message_safe(
        call,
        "📁 <b>Загрузка Telegram-сессии</b>\n\n"
        "Отправьте файл <code>.session</code> от уже авторизованного Telegram-аккаунта.\n\n"
        "После проверки бот получит номер из сессии, а затем попросит цену и категорию.",
        reply_markup=back_to_admin(),
    )
    await answer_safe(call)


@add_account_router.callback_query(F.data == "add_account_telethon")
async def start_add_account(call: CallbackQuery, state: FSMContext):
    """Начать процесс добавления аккаунта."""
    if call.from_user.id not in ADMIN_IDS:
        await answer_safe(call, "❌ У вас нет прав админа.", show_alert=True)
        return
    await state.update_data(password="-")
    await state .set_state (AddAccountState .waiting_for_phone )


    text =(
    f"<tg-emoji emoji-id='{EMOJI_PHONE}'>📞</tg-emoji> <b>Добавление аккаунта через Telethon</b>\n\n"
    "Отправьте номер телефона в международном формате:\n"
    "<blockquote>+79991234567</blockquote>\n"
    f"<tg-emoji emoji-id='{EMOJI_MEGA}'>📣</tg-emoji> <i>На этот номер придёт код авторизации. Убедитесь, что аккаунт не в спам-блоке.</i>"
    )
    await edit_message_safe (call ,text ,reply_markup =back_to_admin ())
    await answer_safe(call)


async def execute_send_code (message :Message ,state :FSMContext ,phone :str ,user_id :int ):
    """Вспомогательная функция для отправки кода через Telethon"""
    try :
        client =await create_telethon_client ()
        phone_code_hash ,error_msg =await send_code_to_phone (client ,phone )

        if not phone_code_hash :
            await remove_cached_client (user_id )
            err_suffix = f"\nПричина: <b>{error_msg}</b>" if error_msg else ""
            await message .answer (f"❌ Не удалось отправить код.{err_suffix}\n\nВведите номер ещё раз:")
            return 

        cache_client (user_id ,client )
        await state .update_data (phone =phone ,phone_code_hash =phone_code_hash )
        await state .set_state (AddAccountState .waiting_for_code )

        await message .answer (
        f"✅ Код успешно отправлен на <code>{phone }</code>\n\n"
        "Введите код из сообщения (5 цифр):"
        )
    except Exception as e :
        await remove_cached_client (user_id )
        await message .answer (f"❌ Ошибка отправки кода: {str (e )}\nПопробуйте /cancel")



@add_account_router .message (AddAccountState .waiting_for_phone ,F .text )
async def process_phone (message :Message ,state :FSMContext ):
    """Обработка номера телефона."""
    phone =message .text .strip ()

    if not phone .startswith ("+")or len (phone )<10 :
        await message .answer ("❌ Неверный формат номера. Введите с плюсом (+):")
        return 

    await message .answer (f"⏳ Отправляем запрос для <code>{phone }</code>...")
    await execute_send_code (message ,state ,phone ,message .from_user .id )


@add_account_router .message (AddAccountState .waiting_for_code ,F .text )
async def process_code (message :Message ,state :FSMContext ):
    """Обработка кода входа."""
    code =message .text .strip ()

    if not code .isdigit ()or len (code )!=5 :
        await message .answer ("❌ Код должен содержать ровно 5 цифр. Попробуйте ещё раз:")
        return 

    data =await state .get_data ()
    phone =data .get ("phone")
    phone_code_hash =data .get ("phone_code_hash")
    client =get_cached_client (message .from_user .id )

    if not client :
        await message .answer ("❌ Сессия истекла. Начните сначала (/cancel).")
        return 

    success ,error ,needs_2fa =await verify_login_code (client ,phone ,code ,phone_code_hash )

    if success :
        await state.set_state(AddAccountState.waiting_for_price)
        await message.answer(
            "🪙 <b>Введите цену аккаунта в Рублях (₽)</b>\n\n"
            "Цена должна быть положительным числом.\n"
            "Пример: <code>150</code>"
        )
    elif needs_2fa :
        await state .set_state (AddAccountState .waiting_for_2fa )
        await message .answer (
        f"<tg-emoji emoji-id='{EMOJI_LOCK}'>🔒</tg-emoji> <b>Включен 2FA пароль.</b>\n\n"
        "Введите облачный пароль от этого аккаунта:"
        )
    else :
        await message .answer (f"❌ Ошибка: {error }\n\nПопробуйте ввести код ещё раз:")


@add_account_router .message (AddAccountState .waiting_for_2fa ,F .text )
async def process_2fa (message :Message ,state :FSMContext ):
    """Обработка 2FA пароля."""
    password =message .text .strip ()
    client =get_cached_client (message .from_user .id )

    if not client :
        await message .answer ("❌ Сессия истекла.")
        return 

    success ,error =await verify_2fa_password (client ,password )

    if success :
        await state .update_data (password =password )
        await state.set_state(AddAccountState.waiting_for_price)
        await message.answer(
            "🪙 <b>Введите цену аккаунта в Рублях (₽)</b>\n\n"
            "Цена должна быть положительным числом.\n"
            "Пример: <code>150</code>"
        )
    else :
        await message .answer (f"❌ {error }\n\nНеверный пароль. Попробуйте ещё раз:")


@add_account_router.message(AddAccountState.waiting_for_price, F.text)
async def process_price(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    import re
    text = message.text.strip()
    if not re.match(r'^\d+(\.\d{1,2})?$', text) or float(text) <= 0:
        await message.answer(
            "❌ Цена должна быть положительным числом с не более чем 2 знаками после запятой.\n"
            "Пример: <code>1.50</code>"
        )
        return
    price = float(text)
    await state.update_data(custom_price=price)

    data = await state.get_data()
    pre_set_slug = data.get("category_slug")

    if pre_set_slug:
        # Категория уже выбрана — сохраняем сразу
        data = await state.get_data()
        session_string = data.get("session_string")
        if session_string:
            await finalize_imported_session(message, state)
            return

        client = get_cached_client(message.from_user.id)
        if not client:
            await message.answer("❌ Сессия истекла. Начните сначала (/cancel).")
            return
        await finalize_and_save_account(message, state, client)
        return

    await state.set_state(AddAccountState.waiting_for_category)

    cats = await get_all_categories()
    rows = []
    for c in cats:
        emoji = c.get("emoji")
        status = "✅" if c["is_active"] else "❌"
        button_text = f"{c['name']} {status}"
        if emoji and emoji.isdigit():
            rows.append([
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"addacc_cat:{c['slug']}",
                    icon_custom_emoji_id=emoji,
                )
            ])
        else:
            display_emoji = emoji or "📁"
            rows.append([
                InlineKeyboardButton(
                    text=f"{display_emoji} {button_text}",
                    callback_data=f"addacc_cat:{c['slug']}",
                )
            ])
    rows.append([InlineKeyboardButton(text="« Отмена", callback_data="admin_home")])

    text_msg = (
        f"📂 <b>Выберите категорию</b> из списка ниже или <b>напишите название категории текстом</b> "
        f"(например: <code>Спамблок группы</code>):\n\n"
        f"<i>(Цена аккаунта: {price:.2f} ₽)</i>"
    )

    await message.answer(
        text_msg,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@add_account_router.message(AddAccountState.waiting_for_category, F.text)
async def process_category_text_input(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    text_val = message.text.strip()
    if not text_val:
        await message.answer("❌ Название категории не может быть пустым. Введите ещё раз:")
        return

    import re
    slug_candidate = re.sub(r'[^a-zA-Z0-9_]', '_', text_val.lower()).strip('_')
    if not slug_candidate:
        slug_candidate = f"cat_{int(datetime.now().timestamp())}"

    from database.db import create_category, get_category, get_all_categories
    cat = await get_category(slug_candidate)
    if not cat:
        all_cats = await get_all_categories()
        found = False
        for c in all_cats:
            if c["name"].lower() == text_val.lower():
                slug_candidate = c["slug"]
                found = True
                break
        if not found:
            await create_category(slug_candidate, text_val, "📁")

    await state.update_data(category_slug=slug_candidate)

    data = await state.get_data()
    if data.get("session_string"):
        await finalize_imported_session(message, state)
        return

    client = get_cached_client(message.from_user.id)
    if not client:
        await message.answer("❌ Сессия истекла. Начните сначала (/cancel).")
        await state.clear()
        return

    await finalize_and_save_account(message, state, client)


@add_account_router.callback_query(AddAccountState.waiting_for_category, F.data.startswith("addacc_cat:"))
async def process_category_selection(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        await answer_safe(call, "❌ Нет прав.", show_alert=True)
        return
    slug = call.data.split(":", 1)[1]
    await state.update_data(category_slug=slug)

    data = await state.get_data()
    await edit_message_safe(call, f"⏳ Сохраняем аккаунт в категорию <b>{slug}</b>...")
    await answer_safe(call)

    if data.get("session_string"):
        await finalize_imported_session(call.message, state)
        return

    client = get_cached_client(call.from_user.id)
    if not client:
        await edit_message_safe(call, "❌ Сессия истекла. Начните сначала (/cancel).")
        await state.clear()
        return

    await finalize_and_save_account(call.message, state, client)


async def finalize_imported_session(message: Message, state: FSMContext):
    """Сохранить уже импортированную авторизованную сессию в магазин."""
    try:
        data = await state.get_data()
        session_string = data.get("session_string")
        phone = data.get("phone")
        category_slug = data.get("category_slug")
        price = float(data.get("custom_price") or 0.35)

        if not session_string or not phone:
            await state.clear()
            await message.answer("❌ Данные сессии потеряны. Начните загрузку заново.")
            return

        code = detect_country_code(phone)

        if not category_slug:
            from database.db import get_all_categories
            auto_country = detect_country(phone)
            all_cats = await get_all_categories()
            for c in all_cats:
                if c["name"].lower() == auto_country.lower():
                    category_slug = c["slug"]
                    break
            if not category_slug:
                category_slug = all_cats[0]["slug"] if all_cats else "us"

        await add_account(
            country=category_slug,
            code=code,
            number=phone,
            password=data.get("password", "-"),
            price=price,
            data=session_string,
        )

        await state.clear()

        from database.db import get_category
        cat_display = await get_category(category_slug)
        cat_name = cat_display["name"] if cat_display else category_slug

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="« В меню", callback_data="admin_home")]
        ])
        await message.answer(
            f"<tg-emoji emoji-id='{EMOJI_CHECK}'>✅</tg-emoji> <b>Сессия успешно добавлена!</b>\n\n"
            f"<tg-emoji emoji-id='{EMOJI_PHONE}'>📞</tg-emoji> Номер: <code>{phone}</code>\n"
            f"📂 Категория: <b>{cat_name}</b>\n"
            f"<tg-emoji emoji-id='5258368777350816286'>🪙</tg-emoji> Цена: <b>{price:.2f} ₽</b>\n\n"
            "<i>Сессия сохранена в базе как StringSession. Исходный .session файл удалён с сервера.</i>",
            reply_markup=kb,
        )
    except Exception as e:
        await state.clear()
        await message.answer(f"❌ Ошибка сохранения сессии в базу: <code>{e}</code>")


async def finalize_and_save_account (message :Message ,state :FSMContext ,client ):
    """Завершить авторизацию и сохранить аккаунт в базу."""
    try :

        session_string ,phone ,country =await finalize_account (client )

        if not session_string :
            await state .clear ()
            await message .answer (f"❌ Ошибка получения сессии: {country }")
            return 

        state_data =await state .get_data ()
        saved_password =state_data .get ("password","-")

        custom_price =state_data .get ("custom_price")
        category_slug =state_data .get ("category_slug")

        # Автоопределение страны по номеру телефона (100+ стран)
        code =detect_country_code (phone)

        # Если категория не выбрана — автоопределяем slug по стране телефона
        if not category_slug:
            from database.db import get_all_categories
            auto_country = detect_country(phone)
            all_cats = await get_all_categories()
            for c in all_cats:
                if c["name"].lower() == auto_country.lower():
                    category_slug = c["slug"]
                    break
            if not category_slug:
                if all_cats:
                    category_slug = all_cats[0]["slug"]
                else:
                    category_slug = "us"

        price =custom_price if custom_price is not None else 0.35

        await add_account (
        country =category_slug ,
        code =code ,
        number =phone ,
        password =saved_password ,
        price =price ,
        data =session_string 
        )

        await state .clear ()

        kb =InlineKeyboardMarkup (inline_keyboard =[
        [InlineKeyboardButton (text ="« В меню",callback_data ="admin_home")]
        ])

        from database.db import get_category
        cat_display = await get_category(category_slug)
        cat_name = cat_display["name"] if cat_display else category_slug

        await message.answer(
            f"<tg-emoji emoji-id='{EMOJI_CHECK}'>✅</tg-emoji> <b>Аккаунт успешно добавлен!</b>\n\n"
            f"<tg-emoji emoji-id='{EMOJI_PHONE}'>📞</tg-emoji> Номер: <code>{phone}</code>\n"
            f"<tg-emoji emoji-id='{EMOJI_LOCK}'>🔒</tg-emoji> Пароль (2FA): <code>{saved_password}</code>\n"
            f"📂 Категория: <b>{cat_name}</b>\n"
            f"<tg-emoji emoji-id='5258368777350816286'>🪙</tg-emoji> Цена: <b>{price:.2f} ₽</b>\n\n"
            f"<i>Товар доступен в магазине.</i>",
            reply_markup=kb,
        )
    except Exception as e :
        await state .clear ()
        await message .answer (f"❌ Ошибка сохранения в базу: {str (e )}")