"""Paged Telegram storefront with server-held quotes and shared checkout."""
from utils.notification_language import send_translated
from utils.i18n import tr
import asyncio
from html import escape
import logging
import secrets
import time

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_IDS
from database import bot_store, coupons
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
        label = tr('{0} · от {1} ₽ · {2} шт.', cat['name'][:35], f"{cat['min_price']:.2f}", str(cat['count'])) if cat['count'] and cat['min_price'] is not None else tr('{0} · Нет в наличии', cat['name'][:35])
        rows.append([InlineKeyboardButton(text=label if emoji.isdigit() else f'{emoji} {label}'.strip(), callback_data=f"buy_{cat['slug']}", icon_custom_emoji_id=emoji if emoji.isdigit() else None)])
    rows += pagination(page, total, bot_store.PAGE_SIZE, 'shop_page')
    rows.append(button(tr('Уведомить о поступлении'), 'stock_menu', 'notifications'))
    rows.append(button(tr('В главное меню'), 'back_main', 'back'))
    text = tr('<b>Каталог аккаунтов</b>\n\nВыберите категорию. Цены учитывают вашу реферальную скидку.')
    if not categories:
        text = tr('<b>Каталог аккаунтов</b>\n\nСейчас свободных аккаунтов нет. Можно подписаться на поступление.')
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
            sku, page = (call.data[4:], 0)
        if not sku or len(sku) > 40:
            raise ValueError(tr('Категория недоступна.'))
        cat = await get_category(sku)
        if not cat or not cat['is_active']:
            raise ValueError(tr('Категория больше недоступна. Обновите каталог.'))
    except ValueError as exc:
        await answer_safe(call, str(exc), show_alert=True)
        return
    accounts, total, page = await bot_store.products(call.from_user.id, sku, page)
    rows = [button(f"#{a['id']:02d} · {mask_phone(a['number'])} · {a['price']:.2f} ₽", f"buy_acc:{a['id']}") for a in accounts]
    rows += pagination(page, total, bot_store.PAGE_SIZE, f'items_page:{sku}')
    if not accounts:
        rows += [button(tr('Уведомить о поступлении'), 'stock_menu', 'notifications')]
    rows += [button(tr('Все категории'), 'back_buy', 'back')]
    text = tr('<b>{0}</b>\n\nСвободно: {1} шт.\nВыберите аккаунт, чтобы проверить цену и гарантию.', f"{escape(cat['name'])}", f'{total}')
    await edit_message_safe(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)


async def show_product(call, state, account_id, promo_code=None):
    item = await bot_store.product(call.from_user.id, account_id)
    if not item:
        await answer_safe(call, tr('Аккаунт уже куплен, скрыт или зарезервирован. Обновите каталог.'), show_alert=True)
        return
    promo = await coupons.preview(call.from_user.id, promo_code) if promo_code else None
    if promo and promo['kind'] != 'discount':
        raise ValueError(tr('Балансовый промокод активируется в профиле.'))
    from decimal import Decimal
    from miniapp.storage import money
    pay_price = money(item['price'] * (1 - Decimal(str(promo['value'])) / 100)) if promo else item['price']
    token = secrets.token_urlsafe(6)
    spam = spam_checks.public(item)
    await state.clear()
    await state.update_data(purchase_quote={'id': account_id, 'price': str(item['price']), 'warranty_hours': item['warranty_hours'], 'spam_status': spam['status'], 'promo_code': promo['code'] if promo else None, 'pay_price': str(pay_price), 'token': token, 'expires': time.time() + 600})
    hours = tr('Не указана') if item['warranty_hours'] is None else tr('{0} ч', f"{item['warranty_hours']}")
    text = tr('<b>Подтверждение покупки</b>\n\nКатегория: <b>{0}</b>\nТовар: <code>#{1}</code>\nTelegram ID: <code>{2}</code>\nГарантия: {3}\nРегистрация: {4}\nPremium: {5}\nСпамблок: {6}\nНомер: <code>{7}</code>\nК оплате: <b>{8} ₽</b>\n\nПосле оплаты номер и данные входа появятся в покупках. После входа смените пароль и привяжите свою почту. Оптовая скидка применяется при оплате корзины в Mini App.', f"{escape(item['name'])}", f'{account_id:02d}', f"{item['telegram_user_id'] or tr('Не сохранён')}", f'{hours}', f"{escape(str(item['registration_date'] or tr('Не указана')))}", f"{(tr('Не проверено') if item['is_premium'] is None else tr('Да') if item['is_premium'] else tr('Нет'))}", f'{escape(spam_checks.description(item))}', f"{escape(mask_phone(item['number']))}", f'{pay_price:.2f}')
    rows = [button(tr('Обновить проверку'), f'buy_acc:{account_id}', 'refresh') if spam['running'] else button(tr('Купить за {0} ₽', f'{pay_price:.2f}'), f'confirm_buy_acc:{account_id}:{token}', 'confirm'), button(tr('Назад к категории'), f"buy_{item['country']}", 'back')]
    rows.insert(1, button(tr('Изменить промокод') if promo else tr('Ввести промокод'), f'purchase_promo:{account_id}', 'reviews'))
    if promo:
        text += tr('\n\nПромокод {0}: скидка {1}%.', f"{escape(promo['code'])}", f"{promo['value']}")
        rows.insert(2, button(tr('Убрать промокод'), f'buy_acc:{account_id}', 'cancel'))
    await edit_message_safe(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)


@shop_router.callback_query(F.data.startswith('buy_acc:'))
async def select_specific_account(call: CallbackQuery, state: FSMContext):
    try:
        account_id = positive_id(call.data.split(':')[1])
    except (ValueError, IndexError):
        await answer_safe(call, tr('Некорректный товар. Откройте каталог заново.'), show_alert=True)
        return
    await show_product(call, state, account_id)


@shop_router.callback_query(F.data.startswith('confirm_buy:') | F.data.startswith('confirm_buy_acc:'))
async def confirm_purchase(call: CallbackQuery, state: FSMContext):
    parts = call.data.split(':')
    if parts[0] == 'confirm_buy':
        rows, _, _ = await bot_store.products(call.from_user.id, parts[1] if len(parts) > 1 else '')
        if rows:
            await show_product(call, state, rows[0]['id'])
        else:
            await answer_safe(call, tr('Обновите каталог: аккаунт недоступен.'), show_alert=True)
        return
    try:
        account_id = positive_id(parts[1])
    except (ValueError, IndexError):
        await answer_safe(call, tr('Некорректный товар.'), show_alert=True)
        return
    async with single_action(call.from_user.id, 'purchase') as acquired:
        if not acquired:
            await answer_safe(call, tr('Покупка уже обрабатывается. Подождите.'), show_alert=True)
            return
        quote = (await state.get_data()).get('purchase_quote') or {}
        if len(parts) != 3 or quote.get('id') != account_id or quote.get('token') != parts[2] or (quote.get('expires', 0) <= time.time()):
            await show_product(call, state, account_id)
            return
        try:
            from decimal import Decimal
            terms = {'spam_status': quote['spam_status']} if 'spam_status' in quote else {}
            if quote.get('promo_code'):
                terms.update(promo_code=quote['promo_code'], expected_total=Decimal(quote['pay_price']))
            result = await checkout(call.from_user.id, account_id, Decimal(quote['price']), warranty_hours=quote['warranty_hours'], **terms)
        except CheckoutError as exc:
            await answer_safe(call, str(exc), show_alert=True)
            if exc.code in {'price_changed', 'terms_changed'}:
                await show_product(call, state, account_id)
            return
        await state.update_data(purchase_quote=None)
        order = await get_purchase_for_user(result['id'], call.from_user.id)
        if not order or order['status'] == 'refunded':
            await answer_safe(call, tr('Откройте «Мои покупки», чтобы проверить статус заказа.'), show_alert=True)
            return
        text = tr('✅ <b>Покупка #{0} оформлена!</b>\n\nНомер: <code>{1}</code>\nПароль 2FA: <code>{2}</code>\nСписано: <b>{3} ₽</b>\nБаланс после покупки: <b>{4} ₽</b>\n\nВведите номер в Telegram и запросите код кнопкой ниже.', f"{result['id']}", f"{escape(order['number'])}", f"{escape(order.get('password') or tr('Не установлен'))}", f"{result['paid_amount']}", f"{result['balance']}")
        await edit_message_safe(call, text, reply_markup=await after_purchase_menu(result['id']))
        await answer_safe(call, tr('Покупка оформлена!'))
        for admin_id in set(ADMIN_IDS):
            try:
                await send_translated(call.bot, admin_id, '🛍 Заказ #{0} · покупатель {1} · {2} ₽', f"{result['id']}", f'{call.from_user.id}', f"{result['paid_amount']}")
            except Exception:
                logger.warning('Sale notification delivery failed')


@shop_router.callback_query(F.data.startswith('get_code:'))
async def deliver_login_code(call: CallbackQuery):
    try:
        purchase_id = positive_id(call.data.split(':')[1])
    except (ValueError, IndexError):
        await answer_safe(call, tr('Некорректный заказ.'), show_alert=True)
        return
    async with single_action(call.from_user.id, f'code:{purchase_id}') as acquired:
        if not acquired:
            await answer_safe(call, tr('Код уже запрашивается. Подождите.'), show_alert=True)
            return
        order = await get_purchase_for_user(purchase_id, call.from_user.id)
        if not order or order['status'] != 'issued' or (not order.get('data')) or (order['data'] == bot_store.DELETED_SESSION):
            await answer_safe(call, tr('Заказ недоступен для получения кода. Откройте «Мои покупки».'), show_alert=True)
            return
        await answer_safe(call, tr('Запрашиваем код…'))
        from services.telethon_code import try_fetch_login_code
        try:
            code = await asyncio.wait_for(try_fetch_login_code(order['data'], order['number']), timeout=30)
        except TimeoutError:
            code = None
        current = await get_purchase_for_user(purchase_id, call.from_user.id)
        if not current or current['status'] != 'issued' or current.get('data') != order['data']:
            await answer_safe(call, tr('Состояние заказа изменилось. Откройте покупку заново.'), show_alert=True)
            return
        if code == 'SESSION_NOT_AUTHORIZED':
            await answer_safe(call, tr('Сессия неактивна. Откройте обращение по заказу в поддержку.'), show_alert=True)
        elif code:
            await edit_message_safe(call, tr('<b>Код входа · заказ #{0}</b>\n\nНомер: <code>{1}</code>\nКод: <code>{2}</code>\nПароль 2FA: <code>{3}</code>\n\nНе передавайте код другим людям. После входа смените пароль и привяжите почту.', f'{purchase_id}', f"{escape(current['number'])}", f'{escape(code)}', f"{escape(current.get('password') or tr('Не установлен'))}"), reply_markup=await after_purchase_menu(purchase_id))
        else:
            await answer_safe(call, tr('Код пока не пришёл. Введите номер в Telegram и повторите через 10 секунд.'), show_alert=True)


class PurchasePromo(StatesGroup):
    waiting = State()


@shop_router.callback_query(F.data.startswith('purchase_promo:'))
async def ask_purchase_promo(call, state):
    try:
        account_id = positive_id(call.data.split(':')[1])
    except (ValueError, IndexError):
        await answer_safe(call, tr('Некорректный товар.'), show_alert=True)
        return
    await state.clear()
    await state.update_data(promo_account_id=account_id)
    await state.set_state(PurchasePromo.waiting)
    await edit_message_safe(call, tr('Введите промокод. Итоговая сумма появится до подтверждения покупки.'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[button(tr('Отмена'), f'buy_acc:{account_id}', 'cancel')]))
    await answer_safe(call)


@shop_router.message(PurchasePromo.waiting,F.text & ~F.text.startswith('/'))
async def enter_purchase_promo(message: Message, state: FSMContext):
    account_id = (await state.get_data()).get('promo_account_id')
    if not account_id:
        await state.clear()
        await message.answer(tr('Откройте товар заново.'))
        return
    async with single_action(message.from_user.id, 'purchase_promo') as acquired:
        if not acquired:
            return
        try:
            promo = await coupons.preview(message.from_user.id, message.text)
            if promo['kind'] == 'balance':
                amount = await coupons.redeem_balance(message.from_user.id, promo['code'])
                await message.answer(tr('Промокод активирован. На баланс зачислено {0} ₽.', f'{amount:.2f}'))
                promo = None
            from types import SimpleNamespace
            screen = await message.answer(tr('Проверяем условия покупки…'))

            async def acknowledge(*args, **kwargs):
                return None
            call = SimpleNamespace(message=screen, from_user=message.from_user, answer=acknowledge, data=f'buy_acc:{account_id}')
            await show_product(call, state, account_id, promo['code'] if promo else None)
        except ValueError as exc:
            await message.answer(str(exc) + tr(' Введите другой код или /cancel.'))


@shop_router.callback_query(F.data.startswith('all_categories:'))
async def all_categories(call, state):
    from database.db import get_all_categories
    await state.clear()
    try:page=page_index(call.data.split(':')[1])
    except (ValueError,IndexError):
        await answer_safe(call,tr('Некорректная страница.'),show_alert=True);return
    cats=await get_all_categories()
    visible=[c for c in cats if c['is_active'] or c['slug'].startswith('section-')]
    page=min(page,max(0,(len(visible)-1)//8))
    rows=[]
    for c in visible[page*8:(page+1)*8]:
        if c['slug'].startswith('section-'):
            suffix=tr('Открыта') if c['is_active'] else tr('В разработке')
            rows.append(button(c['name']+' · '+suffix,'department:'+c['slug']))
        else:rows.append(button(c['name'],'buy_'+c['slug']))
    rows+=pagination(page,len(visible),8,'all_categories')
    rows.append(button(tr('В главное меню'),'back_main','back'))
    await edit_message_safe(call,tr('<b>Все категории</b>\n\nВыберите раздел. Новые направления помечены «В разработке».'),reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)


@shop_router.callback_query(F.data.startswith('department:'))
async def department(call):
    slug=call.data.split(':',1)[1]
    row=await get_category(slug)
    if not row or not slug.startswith('section-'):
        await answer_safe(call,tr('Категория недоступна.'),show_alert=True);return
    status=tr('Пока нет товаров. Загляните позже.') if row['is_active'] else tr('Раздел в разработке. Скоро здесь появятся товары.')
    await edit_message_safe(call,'<b>'+escape(row['name'])+'</b>\n\n'+status,reply_markup=InlineKeyboardMarkup(inline_keyboard=[button(tr('Все категории'),'all_categories:0')]))
    await answer_safe(call)
