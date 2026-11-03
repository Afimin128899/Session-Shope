"""Paged Telegram storefront with server-held quotes and shared checkout."""
import asyncio
from html import escape
import logging
import secrets
import time

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_IDS
from database import bot_store
from database import spam_checks
from database.db import get_category, get_purchase_for_user
from keyboards.pagination import pagination
from keyboards.user_kb import after_purchase_menu
from miniapp.storage import CheckoutError, checkout, mask_phone
from utils.actions import single_action
from utils.button_icons import icon_for
from utils.nav import answer_safe, edit_message_safe
from utils.validation import page_index, positive_id

shop_router = Router()
logger = logging.getLogger(__name__)


def button(text, data, role=None):
    return [InlineKeyboardButton(text=text, callback_data=data, icon_custom_emoji_id=icon_for(role))]


@shop_router.callback_query(F.data.in_({'buy', 'back_buy'}) | F.data.startswith('shop_page:'))
async def open_shop(call: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        page = page_index(call.data.split(':')[1]) if ':' in call.data else 0
    except ValueError as exc:
        await answer_safe(call, str(exc), show_alert=True)
        return
    categories, total, page = await bot_store.categories(call.from_user.id, page)
    rows = []
    for cat in categories:
        emoji = cat.get('emoji') or ''
        label = f"{cat['name'][:35]} · от {cat['min_price']:.2f} ₽ · {cat['count']} шт."
        rows.append([InlineKeyboardButton(
            text=label if emoji.isdigit() else f'{emoji} {label}'.strip(),
            callback_data=f"buy_{cat['slug']}", icon_custom_emoji_id=emoji if emoji.isdigit() else None,
        )])
    rows += pagination(page, total, bot_store.PAGE_SIZE, 'shop_page')
    rows.append(button('Уведомить о поступлении', 'stock_menu', 'notifications'))
    rows.append(button('В главное меню', 'back_main', 'back'))
    text = '<b>Каталог аккаунтов</b>\n\nВыберите категорию. Цены учитывают вашу реферальную скидку.'
    if not categories:
        text = '<b>Каталог аккаунтов</b>\n\nСейчас свободных аккаунтов нет. Можно подписаться на поступление.'
    await edit_message_safe(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)


# Compatibility for code importing the old entry point.
back_buy = open_shop


@shop_router.callback_query((F.data.startswith('buy_') & ~F.data.startswith('buy_acc:') & ~F.data.startswith('buy_curr:')) | F.data.startswith('items_page:'))
async def select_product(call: CallbackQuery):
    try:
        if call.data.startswith('items_page:'):
            _, sku, raw_page = call.data.split(':')
            page = page_index(raw_page)
        else:
            sku, page = call.data[4:], 0
        if not sku or len(sku) > 40:
            raise ValueError('Категория недоступна.')
        cat = await get_category(sku)
        if not cat or not cat['is_active']:
            raise ValueError('Категория больше недоступна. Обновите каталог.')
    except ValueError as exc:
        await answer_safe(call, str(exc), show_alert=True)
        return
    accounts, total, page = await bot_store.products(call.from_user.id, sku, page)
    rows = [button(f"SBA-{a['id']:06d} · {mask_phone(a['number'])} · {a['price']:.2f} ₽", f"buy_acc:{a['id']}") for a in accounts]
    rows += pagination(page, total, bot_store.PAGE_SIZE, f'items_page:{sku}')
    rows += [button('Все категории', 'back_buy', 'back')]
    text = f"<b>{escape(cat['name'])}</b>\n\nСвободно: {total} шт.\nВыберите аккаунт, чтобы проверить цену и гарантию."
    await edit_message_safe(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)


async def show_product(call, state, account_id):
    item = await bot_store.product(call.from_user.id, account_id)
    if not item:
        await answer_safe(call, 'Аккаунт уже куплен, скрыт или зарезервирован. Обновите каталог.', show_alert=True)
        return
    token = secrets.token_urlsafe(6)
    spam = spam_checks.public(item)
    await state.clear()
    await state.update_data(purchase_quote={
        'id': account_id, 'price': str(item['price']), 'warranty_hours': item['warranty_hours'],
        'spam_status': spam['status'],
        'token': token, 'expires': time.time() + 600,
    })
    hours = 'Не указана' if item['warranty_hours'] is None else f"{item['warranty_hours']} ч"
    text = (
        '<b>Подтверждение покупки</b>\n\n'
        f"Категория: <b>{escape(item['name'])}</b>\nТовар: <code>SBA-{account_id:06d}</code>\n"
        f"Telegram ID: <code>{item['telegram_user_id'] or 'Не сохранён'}</code>\n"
        f"Гарантия: {hours}\nРегистрация: {escape(str(item['registration_date'] or 'Не указана'))}\n"
        f"Premium: {'Не проверено' if item['is_premium'] is None else 'Да' if item['is_premium'] else 'Нет'}\n"
        f"Спамблок: {escape(spam_checks.description(item))}\n"
        f"Номер: <code>{escape(mask_phone(item['number']))}</code>\nК оплате: <b>{item['price']:.2f} ₽</b>\n\n"
        'После оплаты номер и данные входа появятся в покупках. После входа смените пароль и привяжите свою почту. '
        'Оптовая скидка и промокод на скидку применяются при оплате корзины в Mini App.'
    )
    rows = [button('Обновить проверку', f'buy_acc:{account_id}', 'refresh') if spam['running'] else button(f"Купить за {item['price']:.2f} ₽", f'confirm_buy_acc:{account_id}:{token}', 'confirm'),
            button('Назад к категории', f"buy_{item['country']}", 'back')]
    await edit_message_safe(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)


@shop_router.callback_query(F.data.startswith('buy_acc:'))
async def select_specific_account(call: CallbackQuery, state: FSMContext):
    try:
        account_id = positive_id(call.data.split(':')[1])
    except (ValueError, IndexError):
        await answer_safe(call, 'Некорректный товар. Откройте каталог заново.', show_alert=True)
        return
    await show_product(call, state, account_id)


@shop_router.callback_query(F.data.startswith('confirm_buy:') | F.data.startswith('confirm_buy_acc:'))
async def confirm_purchase(call: CallbackQuery, state: FSMContext):
    # Old messages never silently purchase a newly priced or different account.
    parts = call.data.split(':')
    if parts[0] == 'confirm_buy':
        rows, _, _ = await bot_store.products(call.from_user.id, parts[1] if len(parts) > 1 else '')
        if rows:
            await show_product(call, state, rows[0]['id'])
        else:
            await answer_safe(call, 'Обновите каталог: аккаунт недоступен.', show_alert=True)
        return
    try:
        account_id = positive_id(parts[1])
    except (ValueError, IndexError):
        await answer_safe(call, 'Некорректный товар.', show_alert=True)
        return
    async with single_action(call.from_user.id, 'purchase') as acquired:
        if not acquired:
            await answer_safe(call, 'Покупка уже обрабатывается. Подождите.', show_alert=True)
            return
        quote = (await state.get_data()).get('purchase_quote') or {}
        if len(parts) != 3 or quote.get('id') != account_id or quote.get('token') != parts[2] or quote.get('expires', 0) <= time.time():
            await show_product(call, state, account_id)
            return
        try:
            from decimal import Decimal
            terms = {'spam_status':quote['spam_status']} if 'spam_status' in quote else {}
            result = await checkout(call.from_user.id, account_id, Decimal(quote['price']), warranty_hours=quote['warranty_hours'], **terms)
        except CheckoutError as exc:
            await answer_safe(call, str(exc), show_alert=True)
            if exc.code in {'price_changed', 'terms_changed'}:
                await show_product(call, state, account_id)
            return
        await state.update_data(purchase_quote=None)
        order = await get_purchase_for_user(result['id'], call.from_user.id)
        if not order or order['status'] == 'refunded':
            await answer_safe(call, 'Откройте «Мои покупки», чтобы проверить статус заказа.', show_alert=True)
            return
        text = (
            f"✅ <b>Покупка #{result['id']} оформлена!</b>\n\n"
            f"Номер: <code>{escape(order['number'])}</code>\n"
            f"Пароль 2FA: <code>{escape(order.get('password') or 'Не установлен')}</code>\n"
            f"Списано: <b>{result['paid_amount']} ₽</b>\nБаланс после покупки: <b>{result['balance']} ₽</b>\n\n"
            'Введите номер в Telegram и запросите код кнопкой ниже.'
        )
        await edit_message_safe(call, text, reply_markup=await after_purchase_menu(result['id']))
        await answer_safe(call, 'Покупка оформлена!')
        for admin_id in set(ADMIN_IDS):
            try:
                await call.bot.send_message(admin_id, f"🛍 Заказ #{result['id']} · покупатель {call.from_user.id} · {result['paid_amount']} ₽")
            except Exception:
                logger.warning('Sale notification delivery failed')


@shop_router.callback_query(F.data.startswith('get_code:'))
async def deliver_login_code(call: CallbackQuery):
    try:
        purchase_id = positive_id(call.data.split(':')[1])
    except (ValueError, IndexError):
        await answer_safe(call, 'Некорректный заказ.', show_alert=True)
        return
    async with single_action(call.from_user.id, f'code:{purchase_id}') as acquired:
        if not acquired:
            await answer_safe(call, 'Код уже запрашивается. Подождите.', show_alert=True)
            return
        order = await get_purchase_for_user(purchase_id, call.from_user.id)
        if not order or order['status'] != 'issued' or not order.get('data') or order['data'] == bot_store.DELETED_SESSION:
            await answer_safe(call, 'Заказ недоступен для получения кода. Откройте «Мои покупки».', show_alert=True)
            return
        await answer_safe(call, 'Запрашиваем код…')
        from services.telethon_code import try_fetch_login_code
        try:
            code = await asyncio.wait_for(try_fetch_login_code(order['data'], order['number']), timeout=30)
        except TimeoutError:
            code = None
        current = await get_purchase_for_user(purchase_id, call.from_user.id)
        if not current or current['status'] != 'issued' or current.get('data') != order['data']:
            await answer_safe(call, 'Состояние заказа изменилось. Откройте покупку заново.', show_alert=True)
            return
        if code == 'SESSION_NOT_AUTHORIZED':
            await answer_safe(call, 'Сессия неактивна. Откройте обращение по заказу в поддержку.', show_alert=True)
        elif code:
            await edit_message_safe(call,
                f"<b>Код входа · заказ #{purchase_id}</b>\n\nНомер: <code>{escape(current['number'])}</code>\n"
                f"Код: <code>{escape(code)}</code>\nПароль 2FA: <code>{escape(current.get('password') or 'Не установлен')}</code>\n\n"
                'Не передавайте код другим людям. После входа смените пароль и привяжите почту.',
                reply_markup=await after_purchase_menu(purchase_id))
        else:
            await answer_safe(call, 'Код пока не пришёл. Введите номер в Telegram и повторите через 10 секунд.', show_alert=True)
