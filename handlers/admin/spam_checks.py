"""Queue official SpamBot checks without keeping Telegram sessions in FSM state."""
from utils.i18n import tr
from html import escape

from aiogram import F, Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_IDS
from database import db, spam_checks
from utils.button_icons import icon_for
from utils.nav import answer_safe, edit_message_safe
from utils.validation import positive_id

spam_router = Router()
spam_router.callback_query.filter(F.message.chat.type == 'private')


def button(text, callback, role):
    return [InlineKeyboardButton(text=text, callback_data=callback, icon_custom_emoji_id=icon_for(role))]


@spam_router.callback_query(F.data.in_({'spam_all', 'spam_all_yes'}))
async def all_accounts(call):
    if call.from_user.id not in ADMIN_IDS:
        await answer_safe(call, tr('Доступ только администратору.'), show_alert=True)
        return
    if call.data == 'spam_all':
        await edit_message_safe(call, tr('<b>Проверить весь остаток?</b>\n\nВ очередь попадут только аккаунты в продаже. Бот отправит /start официальному @SpamBot с каждого аккаунта. Проверка идёт по одному аккаунту; товары в действующем резерве будут проверены после его окончания. Проверявшиеся менее 5 минут назад и аккаунты с ограничением частоты запросов пропускаются.'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[button(tr('Поставить в очередь'), 'spam_all_yes', 'confirm'), button(tr('Отмена'), 'admin_home', 'cancel')]))
    else:
        count = await spam_checks.enqueue(call.from_user.id)
        await edit_message_safe(call, tr('Поставлено в очередь: {0}.\nРезультат и время появятся в карточках аккаунтов. Проверка запускается только по кнопке. После загрузки аккаунт остаётся без подтверждённого результата.', f'{count}'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[button(tr('В админ-панель'), 'admin_home', 'back')]))
    await answer_safe(call)


@spam_router.callback_query(F.data.startswith('spam_check:') | F.data.startswith('spam_show:'))
async def one_account(call):
    if call.from_user.id not in ADMIN_IDS:
        await answer_safe(call, tr('Доступ только администратору.'), show_alert=True)
        return
    try:
        account_id = positive_id(call.data.split(':')[1])
    except (ValueError, IndexError):
        await answer_safe(call, tr('Некорректный товар.'), show_alert=True)
        return
    row = await db.get_account(account_id)
    if not row:
        await answer_safe(call, tr('Товар не найден.'), show_alert=True)
        return
    note = ''
    if call.data.startswith('spam_check:'):
        count = await spam_checks.enqueue(call.from_user.id, account_id)
        note = tr('\n\nПроверка добавлена в очередь.') if count else tr('\n\nПроверка уже идёт, повтор пока недоступен или товар уже продан.')
    await edit_message_safe(call, tr('<b>Спамблок · #{0}</b>\n\n{1}', f'{account_id:02d}', f'{escape(spam_checks.description(row))}') + note + tr('\n\nИсточник: официальный @SpamBot. Результат актуален на момент проверки; состояние может измениться.'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[button(tr('Обновить результат'), f'spam_show:{account_id}', 'refresh'), button(tr('Проверить снова'), f'spam_check:{account_id}', 'warranty'), button(tr('К аккаунту'), f'admin_account_detail:{account_id}', 'back')]))
    await answer_safe(call)
