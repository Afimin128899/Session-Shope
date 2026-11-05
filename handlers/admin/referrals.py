"""Administrator-only editing of future referral rewards."""
from aiogram import F, Router
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database import referrals, admin_web
from handlers.admin.admin_panel import is_admin
from utils.i18n import tr
from utils.button_icons import icon_for
from utils.nav import answer_safe, edit_message_safe

router = Router()
router.message.filter(F.chat.type == 'private')
router.callback_query.filter(F.message.chat.type == 'private')
LABELS = {'referral_signup_bonus': 'За нового реферала, ₽', 'referral_deposit_pct': 'С пополнений, %',
          'referral_daily_limit': 'Лимит в сутки, ₽', 'referral_purchase_pct': 'С покупок, %', 'referral_discount_pct': 'Скидка приглашённому, %'}


class RewardInput(StatesGroup):
    value = State()
    block_id = State()
    list_id = State()


def menu():
    rows = [[InlineKeyboardButton(text=tr(label), callback_data='admin_referral_field:' + key, icon_custom_emoji_id=icon_for('edit'))] for key, label in LABELS.items()]
    rows.append([InlineKeyboardButton(text=tr('Блокировки наград'), callback_data='admin_referral_blocks', icon_custom_emoji_id=icon_for('settings'))])
    rows.append([InlineKeyboardButton(text=tr('Рефералы пользователя'), callback_data='admin_referral_lookup', icon_custom_emoji_id=icon_for('users'))])
    rows.append([InlineKeyboardButton(text=tr('Назад'), callback_data='admin_settings_menu', icon_custom_emoji_id=icon_for('back'))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def text(values):
    return tr('🕒 Лимит в сутки по Москве: {4} ₽\n\n<b>Реферальные награды</b>\n\nЗа нового пользователя: <b>{0} ₽</b>\nС пополнений: <b>{1}%</b>\nС покупок: <b>{2}%</b>\nСкидка приглашённому: <b>{3}%</b>\n\nНаграды получает пригласивший. Проценты считаются от оплаченной суммы, без бонусных зачислений. Изменения действуют на будущие операции; старые начисления и возвраты сохраняют свои суммы.', str(values['signup_bonus']), str(values['deposit_pct']), str(values['bonus_pct']), str(values['discount_pct']), str(values['daily_limit']))


@router.callback_query(F.data == 'admin_referral_settings')
async def show(call, state):
    if not is_admin(call.from_user.id):
        await answer_safe(call, tr('Нет доступа'), show_alert=True)
        return
    await state.clear()
    await edit_message_safe(call, text(await referrals.settings()), reply_markup=menu())
    await answer_safe(call)


@router.callback_query(F.data.startswith('admin_referral_field:'))
async def choose(call, state):
    if not is_admin(call.from_user.id):
        await answer_safe(call, tr('Нет доступа'), show_alert=True)
        return
    key = call.data.partition(':')[2]
    if key not in LABELS:
        await answer_safe(call, tr('Некорректный параметр.'), show_alert=True)
        return
    await state.set_state(RewardInput.value)
    await state.update_data(referral_field=key)
    maximum = '10 000' if key in {'referral_signup_bonus','referral_daily_limit'} else '100'
    await edit_message_safe(call, tr('<b>{0}</b>\n\nВведите число от 0 до {1}, до двух знаков после запятой. 0 отключает эту награду или скидку.', tr(LABELS[key]), maximum), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('Отмена'), callback_data='admin_referral_settings', icon_custom_emoji_id=icon_for('back'))]]))
    await answer_safe(call)


@router.message(RewardInput.value, F.text)
async def save(message, state):
    if not is_admin(message.from_user.id):
        return
    key = (await state.get_data()).get('referral_field')
    if key not in LABELS:
        await state.clear()
        return
    try:
        await admin_web.save_settings(message.from_user.id, {key: message.text.strip().replace(',', '.')})
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await state.clear()
    await message.answer(tr('✅ Реферальные настройки сохранены.') + '\n\n' + text(await referrals.settings()), reply_markup=menu())


@router.callback_query(F.data == 'admin_referral_blocks')
async def show_blocks(call, state):
    if not is_admin(call.from_user.id):
        await answer_safe(call, tr('Нет доступа'), show_alert=True)
        return
    await state.clear()
    data = await referrals.blocks()
    from html import escape
    body = tr('<b>Блокировки реферальных наград</b>\n\nПополнения, покупки и возвраты не блокируются.\n\n')
    body += '\n'.join(f"<code>{item['user_id']}</code> · {escape(item['reason'][:50])}" for item in data['items']) or tr('Список пуст.')
    rows = [[InlineKeyboardButton(text=tr('Заблокировать ID'), callback_data='admin_referral_block')],
            [InlineKeyboardButton(text=tr('Разблокировать ID'), callback_data='admin_referral_unblock')],
            [InlineKeyboardButton(text=tr('Назад'), callback_data='admin_referral_settings')]]
    await edit_message_safe(call, body, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)


@router.callback_query(F.data.in_({'admin_referral_block', 'admin_referral_unblock'}))
async def choose_block(call, state):
    if not is_admin(call.from_user.id):
        await answer_safe(call, tr('Нет доступа'), show_alert=True)
        return
    await state.set_state(RewardInput.block_id)
    await state.update_data(referral_block_enabled=call.data == 'admin_referral_block')
    await edit_message_safe(call, tr('Отправьте Telegram ID и, при желании, причину через пробел. Например: <code>123456789 Причина</code>'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('Отмена'), callback_data='admin_referral_blocks')]]))
    await answer_safe(call)


@router.message(RewardInput.block_id, F.text)
async def save_block(message, state):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.strip().split(maxsplit=1)
    try:
        if not parts or not parts[0].isascii() or not parts[0].isdigit() or len(parts[0]) > 19:
            raise ValueError(tr('Введите корректный Telegram ID.'))
        enabled = (await state.get_data()).get('referral_block_enabled')
        await referrals.set_block(message.from_user.id, int(parts[0]), enabled, parts[1] if len(parts) > 1 else '')
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await state.clear()
    await message.answer(tr('✅ Блокировка реферальных наград обновлена.'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('Блокировки наград'), callback_data='admin_referral_blocks')]]))


async def render_invited(call, owner, page, *, admin=False):
    from html import escape
    data = await referrals.invited(owner, page)
    body = tr('<b>Рефералы пользователя {0}</b>\n\n', owner)
    body += '\n'.join(f"{escape('@'+item['username'] if item['username'] else tr('Пользователь'))} · <code>{item['id']}</code>" for item in data['items']) or tr('Рефералов пока нет.')
    prefix = f'admin_referral_page:{owner}' if admin else 'referral_users'
    rows = []
    navigation = []
    if page:
        navigation.append(InlineKeyboardButton(text='←', callback_data=f'{prefix}:{page-1}'))
    if data['has_more']:
        navigation.append(InlineKeyboardButton(text='→', callback_data=f'{prefix}:{page+1}'))
    if navigation:
        rows.append(navigation)
    rows.append([InlineKeyboardButton(text=tr('Назад'), callback_data='admin_referral_settings' if admin else 'referral_info')])
    await edit_message_safe(call, body, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)


@router.callback_query(F.data == 'admin_referral_lookup')
async def lookup(call, state):
    if not is_admin(call.from_user.id):
        await answer_safe(call, tr('Нет доступа'), show_alert=True)
        return
    await state.set_state(RewardInput.list_id)
    await edit_message_safe(call, tr('Отправьте Telegram ID пользователя, чтобы открыть список его рефералов.'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('Отмена'), callback_data='admin_referral_settings')]]))
    await answer_safe(call)


@router.message(RewardInput.list_id, F.text)
async def lookup_id(message, state):
    if not is_admin(message.from_user.id):
        return
    value = message.text.strip()
    if not value.isascii() or not value.isdigit() or len(value) > 19 or not 0 < int(value) <= 9223372036854775807:
        await message.answer(tr('Введите корректный Telegram ID.'))
        return
    await state.clear()
    await message.answer(tr('Открыть список рефералов пользователя {0}.', value), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('Рефералы пользователя'), callback_data=f'admin_referral_page:{value}:0')]]))


@router.callback_query(F.data.startswith('admin_referral_page:'))
async def lookup_page(call):
    if not is_admin(call.from_user.id):
        await answer_safe(call, tr('Нет доступа'), show_alert=True)
        return
    try:
        _, owner, page = call.data.split(':')
        if not owner.isascii() or not owner.isdigit() or len(owner) > 19 or not 0 < int(owner) <= 9223372036854775807 or not page.isascii() or not page.isdigit() or not 0 <= int(page) <= 10000:
            raise ValueError
    except ValueError:
        await answer_safe(call, tr('Некорректный параметр.'), show_alert=True)
        return
    await render_invited(call, int(owner), int(page), admin=True)
