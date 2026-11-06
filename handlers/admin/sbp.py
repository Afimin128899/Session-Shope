"""Admin switch for the public SBP payment placeholder."""
from aiogram import F, Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
import config
from database import admin_web
from handlers.admin.admin_panel import is_admin
from services import payments
from utils.i18n import tr
from utils.nav import answer_safe, edit_message_safe
from utils.button_icons import icon_for

router = Router()


async def render(call):
    enabled = await payments.sbp_stub_enabled()
    ready = bool(getattr(config, 'PLATEGA_MERCHANT_ID', '') and getattr(config, 'PLATEGA_SECRET', ''))
    body = tr('<b>Оплата через СБП</b>\n\nСумма пополнения: от 1 до 10 000 ₽.\nЗаглушка: <b>{0}</b>\n\nПри включённой заглушке кнопка «Оплатить» показывает временное сообщение. Счёт и платёж не создаются. Уже созданные счета продолжают проверяться.', tr('Включена') if enabled else tr('Выключена'))
    if not ready:
        body += '\n\n' + tr('Для рабочей оплаты настройте Merchant ID и Secret Platega на сервере.')
    rows = [[InlineKeyboardButton(text=tr('Выключить заглушку') if enabled else tr('Включить заглушку'), callback_data='sbp_stub:' + ('0' if enabled else '1'), icon_custom_emoji_id=icon_for('settings'))], [InlineKeyboardButton(text=tr('Назад'), callback_data='admin_settings_menu', icon_custom_emoji_id=icon_for('back'))]]
    await edit_message_safe(call, body, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == 'admin_sbp_settings')
async def show(call):
    if not is_admin(call.from_user.id):
        await answer_safe(call, tr('Нет доступа'), show_alert=True)
        return
    await render(call)
    await answer_safe(call)


@router.callback_query(F.data.in_({'sbp_stub:0', 'sbp_stub:1'}))
async def toggle(call):
    if not is_admin(call.from_user.id):
        await answer_safe(call, tr('Нет доступа'), show_alert=True)
        return
    await admin_web.save_settings(call.from_user.id, {'platega_stub': call.data[-1]})
    await render(call)
    await answer_safe(call, tr('Настройка СБП сохранена.'))
