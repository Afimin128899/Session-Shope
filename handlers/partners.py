"""Owner-approved partner bots, scoped money transfers and bounded content editing."""
import asyncio
import os
import re
import uuid
from html import escape
from pathlib import Path
from contextlib import suppress
from aiogram import Bot,Router,F
from aiogram.filters import Command
from aiogram.fsm.state import State,StatesGroup
from aiogram.types import InlineKeyboardButton as B,InlineKeyboardMarkup as K
from config import ADMIN_IDS
from database import partners
from database.admin_web import rows
from services import partner_tokens
from utils.partner_context import CURRENT,bot_id
from utils.nav import answer_safe,edit_message_safe

router=Router()
router.message.filter(F.chat.type=='private')
router.callback_query.filter(F.message.chat.type=='private')


class PartnerInput(StatesGroup):
    token=State()
    ban=State()
    content=State()
    amount=State()


def kb(rows):return K(inline_keyboard=[[B(text=t,callback_data=d) for t,d in row] for row in rows])


def is_root(user):return CURRENT.get() is None and user in ADMIN_IDS


def own(user):return bool(CURRENT.get() and CURRENT.get()['owner_id']==user)


async def main_username(bot):
    from services.partner_runtime import MAIN
    return (await (MAIN or bot).get_me()).username


async def show_funding(event,p):
    username=await main_username(event.bot)
    from aiogram.types import InlineKeyboardMarkup,InlineKeyboardButton
    from database.db import get_user
    wallet=(await get_user(event.from_user.id)) or {}
    text=f"В этом боте: внесённые {wallet.get('cash_balance',0)} ₽, бонусы {wallet.get('bonus_balance',0)} ₽.\n"+'Пополнение проводится в основном боте. После оплаты переведите внесённые средства в этот бот. Бонусы не переводятся.'
    buttons=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Пополнить через основной бот',url=f'https://t.me/{username}?start=fund_{p["bot_id"]}')]])
    if hasattr(event,'message'):
        await event.message.answer(text,reply_markup=buttons);await answer_safe(event)
    else:await event.answer(text,reply_markup=buttons)


@router.message(Command('partner'))
async def request_entry(message,state):
    if CURRENT.get():return await show_funding(message,CURRENT.get())
    await state.clear()
    mine=await rows('SELECT bot_id,username,status FROM partner_bots WHERE owner_id=%s ORDER BY created_at DESC LIMIT 20',(message.from_user.id,))
    text='<b>Партнёрский бот</b>\nПодключение — после одобрения владельца магазина. Каталог общий, внесённые деньги и бонусы отдельные для каждого бота.\n\n'
    text+='\n'.join(f"@{escape(p['username'])} · {escape(p['status'])}" for p in mine)
    actions=[[('Подать заявку','p:apply')]]
    if is_root(message.from_user.id):actions.append([('Заявки и управление','p:list')])
    await message.answer(text,reply_markup=kb(actions))


@router.message(Command('admin'),lambda event:CURRENT.get() is not None)
async def partner_admin(message,state):
    if not own(message.from_user.id):return await message.answer('Нет доступа.')
    await state.clear()
    await message.answer('Управление партнёрским ботом',reply_markup=kb([[('Заблокировать пользователя','p:ban'),('Снять свою блокировку','p:unban')],[('Оформление меню','pedit:menu:'+str(bot_id()))]]))


@router.callback_query(F.data=='admin_panel_button',lambda event:CURRENT.get() is not None)
async def partner_admin_button(call,state):
    if not own(call.from_user.id):return await answer_safe(call,'Нет доступа.',show_alert=True)
    await state.clear()
    await edit_message_safe(call,'Управление партнёрским ботом',reply_markup=kb([[('Заблокировать пользователя','p:ban'),('Снять свою блокировку','p:unban')],[('Оформление меню','pedit:menu:'+str(bot_id()))]]));await answer_safe(call)


@router.callback_query(F.data.startswith('p:'))
async def partner_actions(call,state):
    parts=call.data.split(':');action=parts[1]
    try:
        if action=='apply':
            if CURRENT.get():raise ValueError('Подключение доступно в основном боте.')
            partner_tokens.cipher();await state.clear();await state.set_state(PartnerInput.token)
            await edit_message_safe(call,'Пришлите токен своего бота из BotFather в этот приватный чат. Сообщение с токеном будет удалено. Токен хранится зашифрованным; запуск — только после одобрения. Отмена: /cancel.')
        elif action=='list':
            if not is_root(call.from_user.id):raise PermissionError('Нет доступа.')
            data=await partners.listing(call.from_user.id)
            buttons=[[(f"@{p['username']} · {p['status']}",f"p:detail:{p['bot_id']}")] for p in data[:50]]
            await edit_message_safe(call,'Партнёрские боты. Выберите заявку или подключённый бот.',reply_markup=kb(buttons))
        elif action=='detail':
            if not is_root(call.from_user.id):raise PermissionError('Нет доступа.')
            p=await partners.get(int(parts[2]))
            if not p:raise ValueError('Бот не найден.')
            identity=p['bot_id'];actions=[]
            if p['status']!='closed':
                actions=[[('Одобрить и включить',f'p:enable:{identity}'),('Приостановить',f'p:pause:{identity}')],[('Закрыть и вернуть остатки',f'p:close:{identity}')],[('Оформление меню',f'pedit:menu:{identity}')]]
            actions.append([('Все боты','p:list')])
            await edit_message_safe(call,f"@{escape(p['username'])}\nВладелец: <code>{p['owner_id']}</code>\nСтатус: {escape(p['status'])}",reply_markup=kb(actions))
        elif action in {'enable','pause','close','close_yes'}:
            if not is_root(call.from_user.id):raise PermissionError('Нет доступа.')
            identity=int(parts[2])
            if action=='close':
                result=await rows('SELECT COUNT(*) AS n,COALESCE(SUM(cash),0) AS cash FROM scoped_wallets WHERE bot_id=%s',(identity,))
                await edit_message_safe(call,f"Закрыть бота {identity}?\nСейчас кошельков: {result[0]['n']}, внесённых средств: {result[0]['cash']} ₽.\nОстаток внесённых средств будет переведён пользователям на основной баланс. Неиспользованные бонусы аннулируются. Закрытие окончательное.",reply_markup=kb([[('Закрыть и вернуть',f'p:close_yes:{identity}')],[('Отмена',f'p:detail:{identity}')]]))
            elif action=='close_yes':await partners.close(call.from_user.id,identity);await edit_message_safe(call,'Бот закрыт. Остатки внесённых средств переведены на основные балансы.',reply_markup=kb([[('Все боты','p:list')]]))
            else:
                await partners.enable(call.from_user.id,identity,action=='enable');await edit_message_safe(call,'Настройка сохранена. Включённый бот запускается автоматически; приостановленный прекращает обслуживание.',reply_markup=kb([[('Назад',f'p:detail:{identity}')]]))
        elif action in {'ban','unban','main_ban','main_unban'}:
            if action.startswith('main_'):
                if not is_root(call.from_user.id):raise PermissionError('Нет доступа.')
                identity=0
            else:
                if not own(call.from_user.id):raise PermissionError('Нет доступа.')
                identity=bot_id()
            await state.clear();await state.update_data(partner_id=identity,ban_enabled=action in {'ban','main_ban'})
            await state.set_state(PartnerInput.ban);await edit_message_safe(call,'Пришлите Telegram ID и причину через пробел. Блокировка действует во всём магазине. Партнёр снимает только свою блокировку; владелец — все. Отмена: /cancel.')
        else:raise ValueError('Действие недоступно.')
        await answer_safe(call)
    except (ValueError,PermissionError) as exc:await answer_safe(call,str(exc),show_alert=True)


@router.message(PartnerInput.token,F.text,~F.text.startswith('/'))
async def receive_token(message,state):
    await state.clear()
    with suppress(Exception):await message.delete()
    if CURRENT.get():return
    token=message.text.strip();bot=None
    try:
        if len(token)>200:raise ValueError
        encrypted=partner_tokens.encrypt(token)
        bot=Bot(token)
        from services.partner_runtime import MAIN
        if bot.id==message.bot.id or (MAIN and bot.id==MAIN.id):raise ValueError
        me=await asyncio.wait_for(bot.get_me(),timeout=12)
        await partners.submit(message.from_user.id,me.id,me.username,encrypted)
    except Exception:
        await message.answer('Не удалось принять заявку: проверьте токен, настройки хранилища или существующую заявку. Токен не показывается в сообщениях.');return
    finally:
        if bot:await bot.session.close()
    await message.answer('Заявка принята. Бот будет включён после одобрения владельца.')
    for admin in set(ADMIN_IDS):
        with suppress(Exception):
            await message.bot.send_message(admin,f"Заявка на партнёрский бот @{escape(me.username)}\nВладелец: <code>{message.from_user.id}</code>",reply_markup=kb([[('Открыть заявку',f'p:detail:{me.id}')]]))


@router.message(PartnerInput.ban,F.text,~F.text.startswith('/'))
async def receive_ban(message,state):
    data=await state.get_data()
    try:
        parts=message.text.split(maxsplit=1)
        if len(parts)!=2 or not parts[0].isascii() or not parts[0].isdigit():raise ValueError('Нужны ID и причина.')
        await partners.ban(message.from_user.id,data['partner_id'],int(parts[0]),parts[1],data['ban_enabled'])
        await state.clear();await message.answer('Блокировка сохранена.' if data['ban_enabled'] else 'Блокировка снята.')
    except (ValueError,PermissionError) as exc:await message.answer(escape(str(exc)))


@router.callback_query(F.data.startswith('pedit:'))
async def edit_content(call,state):
    try:
        parts=call.data.split(':');key=parts[1];identity=int(parts[2])
        if not is_root(call.from_user.id) and not (own(call.from_user.id) and identity==bot_id()):raise PermissionError('Нет доступа.')
        if key=='menu':
            items=[[('Приветственный текст',f'pedit:welcome:{identity}')],[('Главное фото',f'pedit:photo:{identity}')]]
            titles={'btn_buy':'Каталог','btn_balance':'Пополнение','btn_profile':'Профиль','btn_support':'Поддержка','btn_purchases':'Покупки','btn_referral_system':'Рефералы','btn_bonuses':'Бонусы','btn_promo':'Промокод','btn_rules':'Правила','btn_user_settings':'Настройки профиля'}
            items += [[(f"Подпись: {titles[k]}",f'pedit:{k}:{identity}')] for k in sorted(partners.LABELS)]
            items.append([('Назад','admin_panel_button' if CURRENT.get() else ('admin_settings_menu' if identity==0 else f'p:detail:{identity}'))])
            await edit_message_safe(call,'Оформление выбранного бота. Меняются подписи, текст и фото; действия кнопок остаются прежними.',reply_markup=kb(items))
        else:
            if key not in partners.LABELS|{'welcome','photo'}:raise ValueError('Поле недоступно.')
            await state.clear();await state.update_data(partner_id=identity,content_key=key);await state.set_state(PartnerInput.content)
            await edit_message_safe(call,'Пришлите фото до 10 МБ. «Сбросить» — стандартное фото. Отмена: /cancel.' if key=='photo' else 'Пришлите новый текст. Приветствие: до 900 символов, можно {name}; подпись кнопки: до 50. Отправьте «Сбросить» для стандартного оформления. Отмена: /cancel.')
        await answer_safe(call)
    except (ValueError,PermissionError) as exc:await answer_safe(call,str(exc),show_alert=True)


@router.message(PartnerInput.content,F.photo|(F.text&~F.text.startswith('/')))
async def receive_content(message,state):
    data=await state.get_data();identity=data['partner_id'];key=data['content_key']
    try:
        if not is_root(message.from_user.id) and not (own(message.from_user.id) and identity==bot_id()):raise PermissionError('Нет доступа.')
        value=message.text or ''
        if value.casefold()=='сбросить':value=''
        elif key=='photo':
            if not message.photo:raise ValueError('Нужна фотография.')
            photo=message.photo[-1]
            if (photo.file_size or 0)>10*1024*1024:raise ValueError('Фото должно быть до 10 МБ.')
            value=f'partner-assets/{identity}/{uuid.uuid4().hex}.jpg'
            target=Path(os.getenv('PARTNER_ASSET_DIR','data'))/value;target.parent.mkdir(parents=True,exist_ok=True)
            await message.bot.download(photo,destination=target)
        await partners.set_content(message.from_user.id,identity,key,value)
        await state.clear();await message.answer('Оформление сохранено. Откройте /menu в выбранном боте.',reply_markup=kb([[('К редактору меню',f'pedit:menu:{identity}')]]))
    except (ValueError,PermissionError) as exc:await message.answer(escape(str(exc)))


async def funding_entry(message,identity):
    p=await partners.get(identity)
    if not p or p['status']!='enabled':return await message.answer('Партнёрский бот отключён.')
    from database.db import get_user
    profile=await get_user(message.from_user.id)
    await message.answer(f"Пополнение @{escape(p['username'])}\nНа основном внесённом балансе: {profile.get('cash_balance',0)} ₽. Бонусы отдельно: {profile.get('bonus_balance',0)} ₽.\nСначала пополните основной баланс, затем подтвердите перевод сюда.",reply_markup=kb([[('Пополнить основной баланс','topup_balance')],[('Перевести внесённые деньги',f'pfund:amount:{identity}')]]))


@router.callback_query(F.data.startswith('pfund:'))
async def fund_action(call,state):
    if CURRENT.get():return await answer_safe(call,'Перевод доступен только в основном боте.',show_alert=True)
    parts=call.data.split(':')
    try:
        if parts[1]=='amount':
            p=await partners.get(int(parts[2]))
            if not p or p['status']!='enabled':raise ValueError('Бот отключён.')
            await state.clear();await state.update_data(partner_id=p['bot_id']);await state.set_state(PartnerInput.amount)
            await edit_message_safe(call,f"Введите сумму в рублях для @{escape(p['username'])}. Переводится только внесённый баланс, без бонусов. Отмена: /cancel.")
        elif parts[1]=='confirm':
            result=await partners.transfer(call.from_user.id,parts[2]);await state.clear();await edit_message_safe(call,f'Перевод {result} ₽ выполнен. Повторное подтверждение не списывает деньги второй раз.')
        else:raise ValueError('Действие недоступно.')
        await answer_safe(call)
    except (ValueError,PermissionError) as exc:await answer_safe(call,str(exc),show_alert=True)


@router.message(PartnerInput.amount,F.text,~F.text.startswith('/'))
async def receive_amount(message,state):
    if CURRENT.get():return
    try:
        identity=(await state.get_data())['partner_id'];token,value=await partners.quote_transfer(message.from_user.id,identity,message.text.replace(',','.'))
        p=await partners.get(identity)
        await message.answer(f"Перевести {value} ₽ внесённых средств в @{escape(p['username'])}?",reply_markup=kb([[('Подтвердить перевод',f'pfund:confirm:{token}')]]))
    except (ValueError,PermissionError) as exc:await message.answer(escape(str(exc)))
