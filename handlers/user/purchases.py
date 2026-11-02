from html import escape 
from utils.order_status import order_status
from aiogram import Router ,F 
from aiogram .types import CallbackQuery ,InlineKeyboardButton ,InlineKeyboardMarkup 


from database .db import get_purchase_for_user ,get_user_purchases ,complete_user_purchase, get_category, get_all_categories 
from keyboards .user_kb import purchases_list_menu 
from utils import constants as c 
from utils .nav import edit_message_safe, answer_safe 

purchases_router =Router ()

@purchases_router .callback_query (F .data =="my_purchases")
async def my_purchases (call :CallbackQuery, state=None ):
    if state is not None:
        await state.clear()
    """Список всех покупок пользователя"""
    rows =await get_user_purchases (call .from_user .id )
    if not rows :
        await edit_message_safe (
        call ,
        "🛍 <b>Мои покупки</b>\n\nУ вас пока нет покупок.",
        reply_markup =purchases_list_menu ([]),
        )
        await answer_safe(call)
        return 

    categories = await get_all_categories()
    cat_map = {c["slug"]: c for c in categories}

    lines =[]
    for i ,p in enumerate (rows ,1 ):
        slug = p['country']
        cat = cat_map.get(slug)
        if cat:
            cat_name = cat.get("name") or slug
            cat_emoji = cat.get("emoji")
        else:
            cat_name = slug
            cat_emoji = None

        if cat_emoji and cat_emoji.isdigit():
            cat_emoji_html = f" <tg-emoji emoji-id=\"{cat_emoji}\">☺️</tg-emoji>"
        elif cat_emoji:
            cat_emoji_html = f" {cat_emoji}"
        else:
            cat_emoji_html = " <tg-emoji emoji-id=\"5258509201306557640\">📍</tg-emoji>"

        p['country_name'] = cat_name

        lines .append (
        f"<b>{i }. {cat_name}{cat_emoji_html}</b>\n"
        f"   📱 Номер: <code>{p ['number']}</code>\n"
        f"   📅 Дата: {p ['date']}\n"
        f"   Статус: {order_status(p)}\n"
        )

    text ="🛍 <b>История ваших покупок</b>\n\n"+"\n".join (lines )

    await edit_message_safe (
    call ,
    text ,
    reply_markup =purchases_list_menu (list (rows )),
    )
    await answer_safe(call)


@purchases_router .callback_query (F .data .startswith ("open_purchase:"))
async def open_purchase (call :CallbackQuery, state=None ):
    if state is not None:
        await state.clear()
    """Детальный просмотр конкретной покупки"""
    purc_id =int (call .data .split (":")[1 ])
    p =await get_purchase_for_user (purc_id ,call .from_user .id )

    if not p :
        await answer_safe(call, "Запись не найдена.",show_alert =True )
        return 

    if p.get('status') == 'refunded':
        from database.refunds import get_refund
        refund = await get_refund(purc_id, call.from_user.id)
        details = (f"Возвращено: {refund['amount']} {escape(refund['currency'])}\n"
                   f"Причина: {escape(refund['reason'])}" if refund else "Средства возвращены на баланс бота.")
        await edit_message_safe(call, f"<b>Заказ #{purc_id} возвращён</b>\n\n{details}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Поддержка", callback_data=f"purchase_help:{purc_id}")],
                [InlineKeyboardButton(text="Оставить / изменить отзыв", callback_data=f"quality_review:{purc_id}")],
                [InlineKeyboardButton(text="Мои покупки", callback_data="my_purchases")],
            ]))
        await answer_safe(call)
        return

    from database.quality import warranty
    assurance = warranty(p)
    paid_amount = p.get('paid_amount')
    price = float(paid_amount) if paid_amount is not None else 0.0
    currency = p.get('currency') or 'TON'

    if currency.upper() == 'USDT':
        currency_suffix = "USDT <tg-emoji emoji-id=\"5406841020769936275\">☺️</tg-emoji>"
    elif currency.upper() == 'RUB':
        currency_suffix = "₽"
    else:
        currency_suffix = "TON <tg-emoji emoji-id=\"5406976471153545018\">☺️</tg-emoji>"

    formatted_price = (int(price) if price.is_integer() else price) if paid_amount is not None else "не сохранена"

    is_completed = p.get('status') == 'completed' or p.get('data') == '✅ Сессия удалена (Покупка завершена)'


    cat = await get_category(p['country'])
    if cat:
        cat_name = cat.get("name") or p['country']
        cat_emoji = cat.get("emoji")
    else:
        cat_name = p['country']
        cat_emoji = None

    if cat_emoji and cat_emoji.isdigit():
        cat_emoji_html = f" <tg-emoji emoji-id=\"{cat_emoji}\">☺️</tg-emoji>"
    elif cat_emoji:
        cat_emoji_html = f" {cat_emoji}"
    else:
        cat_emoji_html = " <tg-emoji emoji-id=\"5258509201306557640\">📍</tg-emoji>"

    text = (
        f'<tg-emoji emoji-id="5408830295002593386">📤</tg-emoji> <b>Детали покупки #{p ["id"]}</b>\n'
        f"⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
        f"Категория: <b>{cat_name}</b>{cat_emoji_html}\n"
        f"Статус: <b>{order_status(p)}</b>\n"
        f"Гарантия: <b>{escape(assurance['label'])}</b>\n"
        f'<tg-emoji emoji-id="5407025283456835913">📱</tg-emoji> Номер: <code>{p ["number"]}</code>\n'
        f'<tg-emoji emoji-id="5350491749926058609">🔐</tg-emoji> Пароль (2FA): <code>{p .get ("password")or "Нет"}</code>\n'
        f'<tg-emoji emoji-id="5312057711091813718">💳</tg-emoji> Цена: {formatted_price} {currency_suffix}\n'
        f'<tg-emoji emoji-id="5028418466000930064">📆</tg-emoji> Дата: {p ["date"]}\n'
        f"⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
    )

    if is_completed :
        text +=f"\n✅ <b>Данные сессии надежно удалены из базы.</b>"
        kb =InlineKeyboardMarkup (
        inline_keyboard =[
        [InlineKeyboardButton (text ="« Назад",callback_data ="my_purchases")]
        ]
        )
    else :
        text +=(
        f'<tg-emoji emoji-id="5409257566939134596">🔗</tg-emoji> <b>Инструкция:</b>\n'
        f'1. Введите номер в приложении Telegram\n'
        f'2. Нажмите кнопку «Получить код» ниже\n'
        f'3. Если аккаунт спросит пароль — введите его из поля выше\n\n'
        f'<tg-emoji emoji-id="5408943604829794451">⚠️</tg-emoji> <b>Важно:</b>\n'
        f'После входа обязательно поставьте свою почту и смените пароль. '
        f'Затем нажмите «Завершение покупки», чтобы мы удалили данные сессии.'
        )

        kb =InlineKeyboardMarkup (
        inline_keyboard =[
        [
        InlineKeyboardButton (
        text ="Получить код",
        callback_data =f"get_code:{purc_id }"
        ),
        ],
        [
        InlineKeyboardButton (
        text ="Завершение покупки",
        callback_data =f"complete_purchase:{purc_id }",
        ),
        ],
        [
        InlineKeyboardButton (
        text ="« Назад",
        callback_data ="my_purchases"
        ),
        ],
        ]
        )

    kb.inline_keyboard.insert(0, [InlineKeyboardButton(text="Оставить / изменить отзыв", callback_data=f"quality_review:{purc_id}")])
    if assurance['active']:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        until = datetime.fromisoformat(assurance['until']).astimezone(ZoneInfo('Europe/Moscow'))
        text += f"\nГарантия до {until:%d.%m.%Y %H:%M} МСК.\n{escape(assurance['policy'])}"
        kb.inline_keyboard.insert(0, [InlineKeyboardButton(text="Обратиться по гарантии", callback_data=f"quality_warranty:{purc_id}")])

    kb.inline_keyboard.insert(0, [InlineKeyboardButton(
        text="Есть проблема", callback_data=f"purchase_help:{purc_id}",
    )])

    await edit_message_safe (call ,text ,reply_markup =kb )
    await answer_safe(call)


@purchases_router .callback_query (F .data .startswith ("complete_purchase:"))
async def complete_purchase (call :CallbackQuery ):
    """Завершение покупки и очистка сессии в БД"""
    purc_id =int (call .data .split (":")[1 ])
    p =await get_purchase_for_user (purc_id ,call .from_user .id )

    if not p :
        await answer_safe(call, "Запись не найдена.",show_alert =True )
        return 


    if p.get('status') == 'refunded':
        await answer_safe(call, "Заказ уже возвращён на баланс.", show_alert=True)
        return

    await complete_user_purchase (p ['account_id'])

    await answer_safe(call, 
    "✅ Покупка завершена!\n\n"
    "Данные сессии навсегда удалены из нашей базы.",
    show_alert =True 
    )


    await open_purchase (call )
