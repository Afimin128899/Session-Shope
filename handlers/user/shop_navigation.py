"""Country/type/year navigation and atomic bulk buying in the Telegram bot."""
import logging
import secrets
import time
from decimal import Decimal
from html import escape
from types import SimpleNamespace

from aiogram import F, Router
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_IDS
from database import shop_navigation as store, commerce
from database.db import get_purchase_for_user
from keyboards.pagination import pagination
from keyboards.user_kb import after_purchase_menu
from miniapp.storage import checkout_cart, CheckoutError, mask_phone
from utils.actions import single_action
from utils.button_icons import pack_icon_for, pack_text
from utils.i18n import tr
from utils.nav import answer_safe, edit_message_safe
from utils.validation import page_index, positive_id

router = Router()
router.message.filter(F.chat.type == 'private')
router.callback_query.filter(F.message.chat.type == 'private')
log = logging.getLogger(__name__)
TITLES = {'auto': 'Авторег', 'aged': 'Аккаунты с отлегой', 'premium': 'Премиум'}


class Shopping(StatesGroup):
    search = State()
    quantity = State()


def btn(text, data, role=None, green=False):
    return InlineKeyboardButton(text=pack_text(text), callback_data=data, icon_custom_emoji_id=pack_icon_for(role or 'country'), style='success' if green else None)


def kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def price(value):
    return format(Decimal(str(value)), '.2f').rstrip('0').rstrip('.').replace('.', ',')


def country_label(item):
    return tr('{0} · от {1} ₽', item['name'], price(item['min_price']))


def context(mode, nation='all', year=0):
    store.validate(mode, nation, year)
    return ':'.join([mode, nation, str(year)])


async def release(user_id, quote):
    for identity in (quote or {}).get('created_ids', []):
        try:
            await commerce.remove_from_cart(user_id, identity)
        except Exception as exc:
            log.warning('Bulk reservation release failed [%s]', type(exc).__name__)


async def clear(state, user_id):
    previous = (await state.get_data()).get('bulk_quote')
    await state.clear()
    await release(user_id, previous)


async def entry(call, state):
    await clear(state, call.from_user.id)
    rows = [[btn(tr('Авторег'), 'sn:home:auto', 'catalog', True), btn(tr('С отлегой'), 'sn:home:aged', 'calendar', True)],
            [btn(tr('Премиум'), 'sn:home:premium', 'premium', True)], [btn(tr('Назад'), 'back_main', 'back')]]
    await edit_message_safe(call, tr('<b>Купить аккаунт</b>\n\nВыберите вид аккаунта:'), section='catalog', reply_markup=kb(rows))
    await answer_safe(call)


async def show_countries(call, state, mode, *, page=None, query='', bulk=False):
    store.validate(mode)
    await clear(state, call.from_user.id)
    items = await store.countries(call.from_user.id, mode, query)
    rows = []
    if page is None and not bulk and not query:
        rows = [[btn(tr('Самый дешёвый — {0} ₽', price(items[0]['min_price'])) if items else tr('Самый дешёвый · 0 товаров'), f'sn:cheap:{mode}', 'money', True)],
                [btn(tr('Поиск страны'), f'sn:search:{mode}', 'search'), btn(tr('Авторег') if mode == 'premium' else tr('Премиум'), 'sn:home:auto' if mode == 'premium' else 'sn:home:premium', 'money')],
                [btn(tr('Массовая покупка'), f'sn:bulk:{mode}:all:0', 'catalog', True)]]
        featured = max(items, key=lambda item: (item['count'], -item['min_price'])) if items else None
        if featured:
            rows.append([btn(country_label(featured), f"sn:country:{mode}:{featured['nation']}", green=True)])
        visible = [item for item in items if item is not featured][:8]
    else:
        page = min(page or 0, max(0, (len(items) - 1) // 8))
        visible = items[page * 8:(page + 1) * 8]
    for index in range(0, len(visible), 2):
        rows.append([btn(country_label(item), f"sn:{'bc' if bulk else 'country'}:{mode}:{item['nation']}") for item in visible[index:index + 2]])
    if page is None:
        rows.append([btn(tr('Все страны ({0})', len(items)), f'sn:list:{mode}:0', 'catalog')])
    else:
        prefix = f"sn:{'bl' if bulk else 'results' if query else 'list'}:{mode}"
        rows += pagination(page, len(items), 8, prefix)
    rows.append([btn(tr('Назад'), f'sn:home:{mode}' if page is not None or bulk or query else 'buy', 'back')])
    title = tr('Массовая покупка') if bulk else tr(TITLES[mode])
    text = '<b>' + escape(title) + '</b>\n\n' + tr('Выберите страну аккаунта:')
    if mode == 'aged': text += tr('\nПоказаны аккаунты с подтверждённой датой регистрации не менее 30 дней назад.')
    if query: text += tr('\nПоиск: {0}', escape(query))
    if not items: text += tr('\n\n0 товаров. Подходящих аккаунтов сейчас нет.')
    if query: await state.update_data(country_query=query)
    await edit_message_safe(call, text, section='catalog', reply_markup=kb(rows))
    await answer_safe(call)


async def show_years(call, state, mode, nation):
    store.validate(mode, nation)
    await clear(state, call.from_user.id)
    years = await store.years(call.from_user.id, mode, nation)
    buttons = [btn(tr('{0} · от {1} ₽', item['year'], price(item['min_price'])), f"sn:products:{context(mode,nation,item['year'])}:0", 'calendar') for item in years]
    rows = [buttons[index:index + 3] for index in range(0, len(buttons), 3)]
    rows.append([btn(tr('Все годы'), f'sn:products:{context(mode,nation)}:0', 'catalog')])
    rows.append([btn(tr('Назад'), f'sn:home:{mode}', 'back')])
    text = '<b>' + escape(tr(TITLES[mode])) + '</b>\n\n' + tr('{0} — выберите год регистрации аккаунта:', tr(store.COUNTRIES[nation]['name']))
    if not years: text += tr('\n\n0 товаров с подтверждённым годом.')
    await edit_message_safe(call, text, section='catalog', reply_markup=kb(rows))
    await answer_safe(call)


async def show_products(call, state, mode, nation, year=0, page=0):
    store.validate(mode, nation, year)
    await clear(state, call.from_user.id)
    items, total, page = await store.products(call.from_user.id, mode, nation, year, page)
    path = context(mode, nation, year)
    rows = [[btn(f"#{item['id']:02d} · {mask_phone(item['number'])} · {price(item['price'])} ₽", f"sn:item:{item['id']}:{path}:{page}")] for item in items]
    rows += pagination(page, total, 8, f'sn:products:{path}')
    if items: rows.append([btn(tr('Массовая покупка'), f'sn:bulk:{path}', 'catalog', True)])
    else: rows.append([btn(tr('Уведомить о поступлении'), 'stock_menu', 'notifications')])
    rows.append([btn(tr('Назад'), f'sn:country:{mode}:{nation}' if mode == 'aged' else f'sn:home:{mode}', 'back')])
    label = tr(store.COUNTRIES[nation]['name']) if nation != 'all' else tr('Все страны')
    text = '<b>' + escape(tr(TITLES[mode])) + ' · ' + escape(label) + '</b>'
    if year: text += tr('\nГод регистрации: {0}', year)
    text += tr('\n\nВ наличии: {0} товаров.\nВыберите аккаунт:', total)
    await edit_message_safe(call, text, section='catalog', reply_markup=kb(rows))
    await answer_safe(call)


async def quantity_screen(call, state, mode, nation, year=0):
    store.validate(mode, nation, year)
    if nation == 'all':
        return await show_countries(call, state, mode, page=0, bulk=True)
    await clear(state, call.from_user.id)
    _, total, _ = await store.products(call.from_user.id, mode, nation, year)
    path = context(mode,nation,year)
    choices = [qty for qty in [1,5,10,20] if qty <= total]
    rows = [[btn(tr('{0} шт.', qty), f'sn:qty:{path}:{qty}', green=True) for qty in choices]] if choices else []
    if total: rows.append([btn(tr('Ввести количество'), f'sn:custom:{path}', 'edit')])
    rows.append([btn(tr('Назад'), f'sn:home:{mode}', 'back')])
    text = tr('<b>Массовая покупка</b>\n\n{0} · {1}\nВ наличии: {2} товаров.\nВыберите количество, до 20 аккаунтов за покупку.', tr(TITLES[mode]), tr(store.COUNTRIES[nation]['name']), total)
    await edit_message_safe(call, text, section='catalog', reply_markup=kb(rows))
    await answer_safe(call)


async def quote_bulk(call, state, mode, nation, year, quantity):
    async with single_action(call.from_user.id, 'purchase') as acquired:
        if not acquired:
            return await answer_safe(call, tr('Покупка уже обрабатывается. Подождите.'), show_alert=True)
        previous = (await state.get_data()).get('bulk_quote')
        await state.update_data(bulk_quote=None)
        await release(call.from_user.id, previous)
        quote = await store.reserve_bulk(call.from_user.id, mode, nation, quantity, year)
        token = secrets.token_urlsafe(8)
        quote.update(token=token, expires=time.time() + 285, mode=mode, nation=nation, year=year)
        await state.clear()
        await state.update_data(bulk_quote=quote)
        text = tr('<b>Подтверждение массовой покупки</b>\n\n{0} · {1}\nАккаунтов: {2}\nК оплате: <b>{3} ₽</b>\n\nРезерв действует 5 минут. Все аккаунты оплачиваются одной покупкой. После оплаты данные каждого аккаунта придут в этот чат.', tr(TITLES[mode]), tr(store.COUNTRIES[nation]['name']), len(quote['items']), price(quote['total']))
        if Decimal(quote['rate']): text += tr('\nОптовая скидка: {0}%.', price(quote['rate']))
        if year: text += tr('\nГод регистрации: {0}.', year)
        rows = [[btn(tr('Купить за {0} ₽', price(quote['total'])), f'sn:pay:{token}', 'confirm', True)],
                [btn(tr('Отмена'), f'sn:cancel:{token}', 'cancel')]]
        await edit_message_safe(call, text, section='catalog', reply_markup=kb(rows))
        await answer_safe(call)


async def pay_bulk(call, state, token, *, cancel=False):
    async with single_action(call.from_user.id, 'purchase') as acquired:
        if not acquired: return await answer_safe(call, tr('Покупка уже обрабатывается. Подождите.'), show_alert=True)
        quote = (await state.get_data()).get('bulk_quote') or {}
        if quote.get('token') != token:
            return await answer_safe(call, tr('Предложение устарело. Откройте массовую покупку заново.'), show_alert=True)
        if cancel or quote['expires'] <= time.time():
            await state.clear(); await release(call.from_user.id, quote)
            await call.message.answer(tr('Покупка отменена. Средства не списаны.') if cancel else tr('Резерв истёк. Выберите аккаунты заново.'), reply_markup=kb([[btn(tr('Купить аккаунт'),'buy')]]))
            return await answer_safe(call)
        result = await checkout_cart(call.from_user.id, quote['items'], expected_total=Decimal(quote['total']))
        # Invalidate before sending receipts. Delivery errors must never repeat a debit.
        await state.update_data(bulk_quote=None)
        await answer_safe(call, tr('Покупка оформлена!'))
        rows = [[btn(tr('Заказ #{0}', identity), f'open_purchase:{identity}', 'orders')] for identity in result['order_ids']]
        rows.append([btn(tr('Мои покупки'), 'my_purchases', 'orders')])
        summary = tr('<b>Массовая покупка оформлена</b>\n\nАккаунтов: {0}\nСписано: {1} ₽\nОстаток: {2} ₽\n\nДанные доступны в каждом заказе и в «Моих покупках».', len(result['order_ids']), price(result['paid_amount']), price(result['balance']))
        try:
            await edit_message_safe(call, summary, section='orders', reply_markup=kb(rows))
        except Exception as exc:
            log.warning('Bulk summary delivery failed [%s]', type(exc).__name__)
        for identity in result['order_ids']:
            try:
                order = await get_purchase_for_user(identity, call.from_user.id)
                if not order or order['status'] == 'refunded': continue
                text = tr('<b>Заказ #{0}</b>\nНомер: <code>{1}</code>\nПароль 2FA: <code>{2}</code>\n\nЗапросите код входа кнопкой ниже.', identity, escape(order['number']), escape(order.get('password') or tr('Не установлен')))
                await call.message.answer(text, parse_mode='HTML', reply_markup=await after_purchase_menu(identity))
            except Exception as exc:
                log.warning('Bulk receipt delivery failed [%s]', type(exc).__name__)
        from utils.notification_language import send_translated
        for admin in set(ADMIN_IDS):
            try: await send_translated(call.bot, admin, '🛍 Массовая покупка: {0} аккаунтов · покупатель {1} · {2} ₽', len(result['order_ids']), call.from_user.id, result['paid_amount'])
            except Exception as exc: log.warning('Bulk sale alert failed [%s]', type(exc).__name__)


@router.callback_query(F.data.startswith('sn:'))
async def navigate(call, state):
    try:
        parts = call.data.split(':'); action = parts[1]
        if action in {'pay','cancel'} and len(parts) == 3:
            return await pay_bulk(call,state,parts[2],cancel=action == 'cancel')
        if action == 'item' and len(parts) == 7:
            identity=positive_id(parts[2]);mode=parts[3];nation=parts[4];year=int(parts[5]);store.validate(mode,nation,year)
            page=page_index(parts[6])
            from handlers.user.shop import show_product
            return await show_product(call,state,identity,back_callback=f'sn:products:{context(mode,nation,year)}:{page}')
        mode = parts[2]; store.validate(mode)
        if action == 'home' and len(parts) == 3: return await show_countries(call,state,mode)
        if action in {'list','bl','results'} and len(parts) == 4:
            query = (await state.get_data()).get('country_query','') if action == 'results' else ''
            return await show_countries(call,state,mode,page=page_index(parts[3]),query=query,bulk=action == 'bl')
        if action == 'search' and len(parts) == 3:
            await clear(state,call.from_user.id);await state.update_data(shopping_mode=mode);await state.set_state(Shopping.search)
            await edit_message_safe(call,tr('Введите название страны, её код (например, US) или телефонный префикс.'),section='catalog',reply_markup=kb([[btn(tr('Назад'),f'sn:home:{mode}','back')]]));return await answer_safe(call)
        if action in {'country','bc'} and len(parts) == 4:
            nation=parts[3];store.validate(mode,nation)
            if action == 'bc': return await quantity_screen(call,state,mode,nation)
            if mode == 'aged': return await show_years(call,state,mode,nation)
            return await show_products(call,state,mode,nation)
        if action in {'products','bulk','custom','qty'} and len(parts) in {5,6,7}:
            nation=parts[3];year=int(parts[4]);store.validate(mode,nation,year)
            if action == 'products' and len(parts) == 6: return await show_products(call,state,mode,nation,year,page_index(parts[5]))
            if action == 'bulk' and len(parts) == 5: return await quantity_screen(call,state,mode,nation,year)
            if action == 'qty' and len(parts) == 6: return await quote_bulk(call,state,mode,nation,year,positive_id(parts[5]))
            if action == 'custom' and len(parts) == 5:
                await clear(state,call.from_user.id);await state.update_data(shopping_mode=mode,shopping_nation=nation,shopping_year=year);await state.set_state(Shopping.quantity)
                await edit_message_safe(call,tr('Сколько аккаунтов купить? Введите целое число от 1 до 20.'),section='catalog',reply_markup=kb([[btn(tr('Назад'),f'sn:bulk:{context(mode,nation,year)}','back')]]));return await answer_safe(call)
        if action == 'cheap' and len(parts) == 3:
            items,_,_=await store.products(call.from_user.id,mode,quantity=1)
            if not items: return await answer_safe(call,tr('0 товаров. Сейчас свободных аккаунтов нет.'),show_alert=True)
            await clear(state,call.from_user.id)
            from handlers.user.shop import show_product
            return await show_product(call,state,items[0]['id'],back_callback=f'sn:home:{mode}')
        raise ValueError(tr('Кнопка устарела. Откройте «Купить аккаунт» заново.'))
    except (ValueError,IndexError) as exc:
        await answer_safe(call,str(exc) or tr('Некорректные параметры.'),show_alert=True)


async def message_call(message):
    screen = await message.answer(tr('Загружаем каталог…'))
    async def acknowledge(*args, **kwargs): pass
    return SimpleNamespace(message=screen,from_user=message.from_user,answer=acknowledge)


@router.message(Shopping.search,F.text & ~F.text.startswith('/'))
async def search(message,state):
    query=message.text.strip()
    if not query or len(query)>64: return await message.answer(tr('Введите название страны, до 64 символов.'))
    mode=(await state.get_data()).get('shopping_mode','auto')
    await show_countries(await message_call(message),state,mode,page=0,query=query)


@router.message(Shopping.quantity,F.text & ~F.text.startswith('/'))
async def custom_quantity(message,state):
    try:
        quantity=positive_id(message.text.strip())
        if quantity>20: raise ValueError(tr('Количество: от 1 до 20.'))
        data=await state.get_data()
        await quote_bulk(await message_call(message),state,data['shopping_mode'],data['shopping_nation'],data['shopping_year'],quantity)
    except ValueError as exc:
        await message.answer(str(exc))
