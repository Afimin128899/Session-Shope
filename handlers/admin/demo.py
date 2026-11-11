"""Clearly namespaced, admin-only training actions."""
from utils.i18n import tr
from html import escape
from aiogram import Router,F
from aiogram.types import InlineKeyboardButton,InlineKeyboardMarkup,WebAppInfo
from config import ADMIN_IDS
from services.demo import STORE
from utils.button_icons import icon_for
from utils.miniapp import customer_miniapp_url
from utils.nav import answer_safe,edit_message_safe

DEMO_ROUTER=Router()


def button(label,data,role='settings'):
    return [InlineKeyboardButton(text=label,callback_data=data,icon_custom_emoji_id=icon_for(role))]


@DEMO_ROUTER.callback_query(F.data.startswith('demo:'))
async def demo(call, state):
    if call.from_user.id not in ADMIN_IDS:
        await answer_safe(call, tr('Доступ только администратору.'), show_alert=True)
        return
    pieces = call.data.split(':')
    if call.data == 'demo:open':
        await state.clear()
        view = STORE.enter(call.from_user.id)
    elif call.data == 'demo:exit':
        STORE.exit(call.from_user.id)
        await state.clear()
        await edit_message_safe(call, tr('Тестовый режим закрыт. Теперь доступны рабочие операции.'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[button(tr('В рабочую админку'), 'admin_home', 'home')]))
        await answer_safe(call)
        return
    else:
        try:
            action = pieces[1]
            body = {'action': action, 'generation': pieces[2]}
            if action == 'reset_ask':
                view = STORE.view(call.from_user.id)
                if body['generation'] != view['generation']:
                    raise ValueError(tr('Обновите тестовый экран.'))
                await edit_message_safe(call, tr('Сбросить только ваш учебный баланс, счета и покупки?'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[button(tr('Сбросить учебные данные'), f"demo:reset:{view['generation']}", 'confirm'), button(tr('Отмена'), 'demo:open', 'cancel')]))
                await answer_safe(call)
                return
            if action in {'buy', 'add', 'refund', 'code', 'complete'}:
                body['id'] = int(pieces[3])
            if action == 'buy':
                body['promo'] = 'DEMO10' if len(pieces) > 4 and pieces[4] == 'promo' else ''
            if action == 'invoice':
                body.update(provider=pieces[3], amount='100', stars=100)
            if action == 'pay':
                body['invoice_id'] = pieces[3]
            view = STORE.action(call.from_user.id, body)
        except (ValueError, IndexError) as exc:
            await answer_safe(call, str(exc) or tr('Обновите учебный экран.'), show_alert=True)
            return
    generation = view['generation']
    text = tr('<b>ТЕСТОВЫЙ МАГАЗИН</b>\n\nУчебный баланс: <b>') + view['balance'] + tr(' ₽</b>\nУчебные покупки и пополнения полностью изолированы от рабочего магазина.\n\n')
    text += tr('Последнее действие: ') + escape(view['events'][-1] if view['events'] else tr('Выберите сценарий.'))
    rows = []
    for p in view['products']:
        if p['available']:
            rows.append(button(f"{p['name']} · {p['price']} ₽", f"demo:buy:{generation}:{p['id']}", 'catalog'))
            rows.append(button(tr('Купить с учебным DEMO10 (−10%)'), f"demo:buy:{generation}:{p['id']}:promo", 'reviews'))
    for provider, label in [('xrocket', 'xRocket'), ('crypto', 'Crypto Pay'), ('lave', 'Laveshka'), ('stars', '100 ⭐ → 120 ₽')]:
        rows.append(button(tr('Создать учебный счёт · ') + label, f'demo:invoice:{generation}:{provider}', 'money'))
    for invoice in view['invoices']:
        if not invoice['paid']:
            rows.append(button(tr('Подтвердить учебную оплату {0} ₽', f"{invoice['amount']}"), f"demo:pay:{generation}:{invoice['id']}", 'confirm'))
    for order in view['orders']:
        text += tr('\n\nУчебный заказ #{0} · {1} ₽ · {2}', f"{order['id']}", f"{order['paid']}", f"{order['status']}")
        if order['status'] == 'issued':
            rows.append(button(tr('Учебный код #{0}', f"{order['id']}"), f"demo:code:{generation}:{order['id']}", 'code'))
        if order['status'] != 'refunded':
            rows.append(button(tr('Учебный возврат #{0}', f"{order['id']}"), f"demo:refund:{generation}:{order['id']}", 'money'))
    rows.append(button(tr('Учебное колесо удачи'), f'demo:reward:{generation}', 'reviews'))
    url = customer_miniapp_url()
    if url:
        rows.append([InlineKeyboardButton(text=tr('Открыть тестовый Mini App'), web_app=WebAppInfo(url=url + '/demo'), icon_custom_emoji_id=icon_for('catalog'))])
    rows.append(button(tr('Сбросить учебные данные'), f'demo:reset_ask:{generation}', 'refresh'))
    rows.append(button(tr('В рабочий магазин'), 'demo:exit', 'back'))
    await edit_message_safe(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)
