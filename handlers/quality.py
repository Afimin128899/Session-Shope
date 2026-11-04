"""Buyer reviews, warranty claims and admin product characteristics."""
from datetime import datetime, timezone
from html import escape
from zoneinfo import ZoneInfo
from aiogram import Router,F
from aiogram.fsm.state import StatesGroup,State
from aiogram.types import InlineKeyboardButton,InlineKeyboardMarkup
from config import ADMIN_IDS
from database import db, quality, coupons, tickets
from handlers.tickets import notify
from utils.nav import answer_safe, edit_message_safe

quality_router=Router()
quality_router.message.filter(F.chat.type=='private')
quality_router.callback_query.filter(F.message.chat.type=='private')


class Input(StatesGroup):
    review=State()
    warranty=State()
    features=State()
    discount=State()


def back(order):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='К заказу',callback_data=f'open_purchase:{order}')]])


def identifier(raw):
    if not raw.isascii() or not raw.isdigit() or not 0<int(raw)<=2147483647: raise ValueError('Некорректный ID.')
    return int(raw)


@quality_router.callback_query(F.data.startswith('quality_review:'))
async def begin_review(call,state):
    try:
        order=identifier(call.data.split(':',1)[1])
        if not await db.get_purchase_for_user(order,call.from_user.id): raise ValueError('Покупка не найдена.')
    except ValueError as exc:
        await answer_safe(call,str(exc),show_alert=True);return
    await state.clear();await state.update_data(quality_order=order);await state.set_state(Input.review)
    await edit_message_safe(call,'Отправьте оценку и отзыв: <code>5 Всё хорошо, вход работает</code>\nОтзыв будет публичным, имя и Telegram ID не публикуются. Не указывайте номер, пароль и коды входа. До 500 символов. Повторный отзыв обновит предыдущий.',reply_markup=back(order))
    await call.answer()


@quality_router.message(Input.review,F.text)
async def submit_review(message,state):
    try:
        rating,body=message.text.strip().split(maxsplit=1)
        order=(await state.get_data())['quality_order']
        await quality.save_review(message.from_user.id,order,int(rating),body)
    except (ValueError,KeyError) as exc:
        await message.answer(escape(str(exc)) if str(exc) else 'Формат: 5 Текст отзыва');return
    await state.clear();await message.answer('✅ Отзыв опубликован. Спасибо!',reply_markup=back(order))


@quality_router.callback_query(F.data.startswith('quality_warranty:'))
async def begin_warranty(call,state):
    try:
        order=identifier(call.data.split(':',1)[1]);row=await db.get_purchase_for_user(order,call.from_user.id)
        if not row or not quality.warranty(row)['active']: raise ValueError('Гарантия не действует. Обычная поддержка остаётся доступной.')
    except ValueError as exc:
        await answer_safe(call,str(exc),show_alert=True);return
    await state.clear();await state.update_data(quality_order=order);await state.set_state(Input.warranty)
    await edit_message_safe(call,'Опишите проблему со входом (до 500 символов). Не отправляйте пароли, коды и сессии. Срок гарантии проверяется при отправке.',reply_markup=back(order));await call.answer()


@quality_router.message(Input.warranty,F.text)
async def submit_warranty(message,state):
    try:
        order=(await state.get_data())['quality_order']
        ticket=await tickets.create_ticket(message.from_user.id,order,message.text,warranty=True)
    except (ValueError,KeyError) as exc:
        await message.answer(escape(str(exc)));return
    await state.clear()
    await message.answer(f'✅ Гарантийное обращение #{ticket} сохранено. Поддержка ответит в боте.',reply_markup=back(order))
    await notify(message.bot,ADMIN_IDS,ticket,'Новое гарантийное обращение.')


@quality_router.callback_query(F.data.startswith('quality_features:'))
async def begin_features(call,state):
    if call.from_user.id not in ADMIN_IDS:
        await answer_safe(call,'Нет доступа.',show_alert=True);return
    try:
        account=identifier(call.data.split(':',1)[1]);row=await db.get_account(account)
        if not row: raise ValueError('Аккаунт не найден.')
    except ValueError as exc:
        await answer_safe(call,str(exc),show_alert=True);return
    await state.clear();await state.update_data(quality_account=account);await state.set_state(Input.features)
    await edit_message_safe(call,f"Товар SBA-{account:06d}. Гарантия сейчас: {row.get('warranty_hours') if row.get('warranty_hours') is not None else 'не указана'} ч.\nОтправьте четыре строки:\n<code>24\n2024-01-31\nда\nОписание аккаунта</code>\n1. Гарантия в часах, 0 = без гарантии (до 8760).\n2. Проверенная дата регистрации или ?.\n3. Premium: да / нет / ?.\n4. Описание до 500 символов или -.\nСохраняйте только проверенные характеристики. Проданные заказы сохранят прежние условия.")
    await call.answer()


@quality_router.message(Input.features,F.text)
async def submit_features(message,state):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        hours,registered,premium,note=message.text.strip().split('\n',3)
        if premium.strip().lower() not in {'да','нет','?'}: raise ValueError('Premium: да, нет или ?.')
        account=(await state.get_data())['quality_account']
        await quality.edit_characteristics(message.from_user.id,account,hours=int(hours),registered=None if registered.strip()=='?' else registered.strip(),premium={'да':True,'нет':False,'?':None}[premium.strip().lower()],note='' if note.strip()=='-' else note.strip())
    except (ValueError,KeyError) as exc:
        await message.answer('Не сохранено. '+escape(str(exc)));return
    await state.clear();await message.answer('✅ Характеристики и гарантия сохранены. Действие записано в журнал.')


@quality_router.callback_query(F.data=='quality_discount')
async def begin_discount(call,state):
    if call.from_user.id not in ADMIN_IDS:
        await answer_safe(call,'Нет доступа.',show_alert=True);return
    await state.clear();await state.set_state(Input.discount)
    await edit_message_safe(call,'Отправьте код, процент и общий лимит: <code>SBAND10 10 100</code>\nКаждый покупатель применяет код один раз при оплате корзины. Скидка применяется после личной скидки. Старые промокоды пополнения баланса продолжат работать.')
    await call.answer()


@quality_router.message(Input.discount,F.text)
async def submit_discount(message,state):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        code,percent,limit=message.text.split()
        await coupons.create_discount(message.from_user.id,code,percent,int(limit))
    except ValueError as exc:
        await message.answer('Не создано. '+escape(str(exc)));return
    await state.clear();await message.answer('✅ Промокод скидки создан.')


@quality_router.callback_query(F.data.startswith('customer_activity:'))
async def removed_activity(call):
    # Old Telegram messages may still contain this button.
    await answer_safe(call,'Этот раздел удалён из пользовательского меню.',show_alert=True)


@quality_router.callback_query(F.data.startswith('quality_reviews:'))
async def show_reviews(call):
    raw=call.data.split(':',1)[1]
    if not raw.isascii() or not raw.isdigit() or int(raw)>1000:
        await answer_safe(call,'Некорректная страница.',show_alert=True);return
    page=int(raw);data=await quality.reviews(page,per_page=1)
    # One review per Telegram page keeps even maximum escaped text under 4096 chars.
    rows=[]
    text=f"<b>Отзывы покупателей</b>\nОценка: {data['average'] or '—'} / 5 · Отзывов: {data['count']}\n\n"
    for item in data['items']:
        text+=f"<b>{item['rating']} / 5 · Покупатель</b>\n{escape(item['body'])}\n\n"
    if not data['items']: text+='Отзывы пока не оставлены. Написать свой можно в деталях покупки.'
    if page: rows.append([InlineKeyboardButton(text='Новее',callback_data=f'quality_reviews:{page-1}')])
    if data['has_more'] and page<1000: rows.append([InlineKeyboardButton(text='Ранее',callback_data=f'quality_reviews:{page+1}')])
    rows.append([InlineKeyboardButton(text='В меню',callback_data='main_menu')])
    from utils.nav import edit_message_safe
    await edit_message_safe(call,text,reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()
