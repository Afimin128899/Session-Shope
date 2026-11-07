"""Manual inventory review, independent sales pause and maintenance notices."""
from utils.i18n import tr
import secrets
from html import escape

from aiogram import Router, F
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_IDS
from database import admin_web
from database.shop_control import set_review, public_status
from utils.nav import edit_message_safe, answer_safe

control_router = Router()


class ControlInput(StatesGroup):
    reason = State()
    confirm = State()
    notice = State()


def button(text, data):
    return [InlineKeyboardButton(text=text, callback_data=data)]


def back():
    return InlineKeyboardMarkup(inline_keyboard=[button(tr('В админ-панель'), 'admin_home')])


@control_router.callback_query(F.data == 'shop_status')
async def show_shop_control(call, state):
    if call.from_user.id not in ADMIN_IDS:
        await answer_safe(call, tr('Нет доступа.'), show_alert=True)
        return
    await state.clear()
    settings = await admin_web.settings()
    status = public_status(settings)
    text = tr('⚙️ <b>Режимы магазина</b>\n\n🛠 Техработы: <b>{0}</b>\n⏸ Продажи: <b>{1}</b>\n\n📝 Причина техработ: {2}\n🕒 Ориентир: {3}\n🛍 Сообщение об остановке продаж: {4}\n\nПри остановке продаж каталог, купленные аккаунты, коды и поддержка доступны. Полные техработы закрывают интерфейс покупателей. Подтверждённые оплаты обрабатываются в обоих режимах.', f"{(tr('включены') if status['maintenance'] else tr('выключены'))}", f"{(tr('приостановлены') if status['sales_paused'] else tr('открыты'))}", f"{escape(status['reason'])}", f"{escape(status['eta'])}", f"{escape(status['sales_reason'])}")
    rows = [button(tr('🛠 Выключить техработы') if status['maintenance'] else tr('🛠 Включить техработы'), 'shop_mode:maintenance'), button(tr('▶️ Открыть продажи') if status['sales_paused'] else tr('⏸ Приостановить продажи'), 'shop_mode:sales'), button(tr('📝 Причина техработ'), 'shop_notice:maintenance_reason'), button(tr('🕒 Время завершения'), 'shop_notice:maintenance_eta'), button(tr('🛍 Причина остановки продаж'), 'shop_notice:sales_pause_reason'), button(tr('🔎 Аккаунты на проверке'), 'review_list:0'), button(tr('В админ-панель'), 'admin_home')]
    await edit_message_safe(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), section='settings')
    await answer_safe(call)


@control_router.callback_query(F.data.in_({'shop_mode:maintenance', 'shop_mode:sales'}))
async def toggle_mode(call, state):
    if call.from_user.id not in ADMIN_IDS:
        return
    key = 'sales_paused' if call.data.endswith(':sales') else 'maintenance_mode'
    # Toggle under a lock; two admin clicks cannot overwrite one another's read.
    from database.admin_tools import _transaction, _record
    async with _transaction() as cur:
        await cur.execute('INSERT IGNORE INTO settings(`key`,`value`) VALUES(%s,%s)', (key, '0'))
        await cur.execute('SELECT `value` FROM settings WHERE `key`=%s FOR UPDATE', (key,))
        row = await cur.fetchone()
        value = '0' if row['value'] == '1' else '1'
        await cur.execute('UPDATE settings SET `value`=%s WHERE `key`=%s', (value, key))
        await _record(cur, call.from_user.id, 'shop_mode', 'settings', key, {'value': value})
    await show_shop_control(call, state)


@control_router.callback_query(F.data.startswith('shop_notice:'))
async def notice_entry(call, state):
    if call.from_user.id not in ADMIN_IDS:
        return
    key = call.data.split(':', 1)[1]
    if key not in {'maintenance_reason', 'maintenance_eta', 'sales_pause_reason'}:
        return
    await state.clear()
    await state.set_state(ControlInput.notice)
    await state.update_data(notice_key=key)
    await edit_message_safe(call, tr('📝 Введите текст до 200 символов. Он будет показан покупателям. Для времени укажите, например: «Сегодня около 18:00 МСК»; это ориентир, автоматического открытия нет.'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[button(tr('Отмена'), 'shop_status')]), section='settings')
    await answer_safe(call)


@control_router.message(ControlInput.notice, F.text & ~F.text.startswith('/'))
async def notice_save(message, state):
    if message.from_user.id not in ADMIN_IDS:
        return
    value = message.text.strip()
    if not 1 <= len(value) <= 200:
        await message.answer(tr('Введите от 1 до 200 символов.'))
        return
    saved = await state.get_data()
    await admin_web.save_settings(message.from_user.id, {saved['notice_key']: value})
    await state.clear()
    await message.answer(tr('✅ Сообщение обновлено.'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[button(tr('Режимы магазина'), 'shop_status')]))


@control_router.callback_query(F.data.startswith('review_list:'))
async def review_list(call, state):
    if call.from_user.id not in ADMIN_IDS:
        return
    from utils.validation import page_index
    try:
        page = page_index(call.data.split(':')[1])
    except ValueError:
        await answer_safe(call, tr('Проверьте номер страницы.'))
        return
    await state.clear()
    result = await admin_web.stock(status='review', page=page)
    rows = [button(f"#{r['id']:02d} · {r['number']}", f"admin_account_detail:{r['id']}") for r in result['items']]
    if page:
        rows.append(button(tr('← Назад'), f'review_list:{page - 1}'))
    if result['has_more']:
        rows.append(button(tr('Далее →'), f'review_list:{page + 1}'))
    rows.append(button(tr('В админ-панель'), 'admin_home'))
    await edit_message_safe(call, tr('🔎 <b>На проверке</b>\n\nЭти аккаунты скрыты из продажи до решения администратора.') + (tr('\n\nСписок пуст.') if not result['items'] else ''), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), section='inventory')
    await answer_safe(call)


@control_router.callback_query(F.data.startswith('review:'))
async def review_entry(call, state):
    if call.from_user.id not in ADMIN_IDS:
        return
    from utils.validation import positive_id
    try:
        _, action, raw_id = call.data.split(':')
        if action not in {'hold', 'release'}:
            raise ValueError
        account = positive_id(raw_id)
    except ValueError:
        await answer_safe(call, tr('Некорректный товар.'))
        return
    await state.clear()
    await state.update_data(review_id=account, review_enabled=action == 'hold')
    await state.set_state(ControlInput.reason)
    await edit_message_safe(call, tr('📝 Укажите причину решения: 3–500 символов. После этого появится подтверждение. Причина видна только администраторам.'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[button(tr('Отмена'), f'admin_account_detail:{account}')]), section='inventory')
    await answer_safe(call)


@control_router.message(ControlInput.reason, F.text & ~F.text.startswith('/'))
async def review_reason(message, state):
    if message.from_user.id not in ADMIN_IDS:
        return
    reason = message.text.strip()
    if not 3 <= len(reason) <= 500:
        await message.answer(tr('Укажите причину: 3–500 символов.'))
        return
    saved = await state.get_data()
    token = secrets.token_hex(8)
    await state.update_data(review_reason=reason, review_token=token)
    await state.set_state(ControlInput.confirm)
    action = tr('Отправить на проверку') if saved['review_enabled'] else tr('Вернуть в продажу')
    text = tr('🔎 <b>{0}: #{1}</b>\n\nПричина: {2}\n\n', f'{action}', f"{saved['review_id']:02d}", f'{escape(reason)}')
    text += tr('Товар будет скрыт из каталога, резерв и запись в корзине отменятся. Деньги не списываются.') if saved['review_enabled'] else tr('Товар станет доступен в активной категории. Проверка @SpamBot будет поставлена в очередь.')
    from utils.section_banners import answer_screen
    await answer_screen(message, text, section='inventory', reply_markup=InlineKeyboardMarkup(inline_keyboard=[button(tr('Подтвердить решение'), f'review_apply:{token}'), button(tr('Отмена'), f"admin_account_detail:{saved['review_id']}")]))


@control_router.callback_query(F.data.startswith('review_apply:'))
async def review_confirm(call, state):
    if call.from_user.id not in ADMIN_IDS:
        return
    saved = await state.get_data()
    if not saved.get('review_token') or saved['review_token'] != call.data.split(':', 1)[1]:
        await answer_safe(call, tr('Подтверждение устарело. Откройте товар заново.'), show_alert=True)
        return
    try:
        await set_review(call.from_user.id, saved['review_id'], saved['review_enabled'], saved['review_reason'])
    except ValueError as exc:
        await answer_safe(call, str(exc), show_alert=True)
        return
    await state.clear()
    await edit_message_safe(call, tr('✅ Решение сохранено в журнале.'), section='inventory', reply_markup=InlineKeyboardMarkup(inline_keyboard=[button(tr('Открыть товар'), f"admin_account_detail:{saved['review_id']}"), button(tr('На проверке'), 'review_list:0')]))
    await answer_safe(call)
