"""Helper's advertising desk, independent of owner-only admin actions."""
from html import escape
from datetime import timezone
from zoneinfo import ZoneInfo
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K, WebAppInfo
from database import advertising as ads
from config import ADMIN_IDS
from utils.nav import answer_safe, edit_message_safe

router=Router()


class AdvertisingInput(StatesGroup):
    name=State()


def helper_keyboard():
    rows=[[B(text='Реклама',callback_data='advertising:list')]]
    from utils.miniapp import admin_miniapp_url
    url=admin_miniapp_url()
    if url:
        rows.append([B(text='Открыть кабинет помощника',web_app=WebAppInfo(url=url))])
    rows.append([B(text='В магазин',callback_data='main_menu')])
    return K(inline_keyboard=rows)


async def helper_entry(message,state):
    if not await ads.is_helper(message.from_user.id):
        return
    await state.clear()
    await message.answer('<b>Кабинет помощника</b>\nРекламные ссылки и привлечённые пользователи.',reply_markup=helper_keyboard())


@router.message(Command('helper'))
async def manage_helper(message,command):
    if message.from_user.id not in ADMIN_IDS:
        return
    parts=(command.args or '').split()
    try:
        if len(parts)!=2 or parts[1] not in {'on','off'} or not parts[0].isascii() or not parts[0].isdigit():
            raise ValueError('Назначить: /helper ID on\nСнять роль: /helper ID off\nПользователь должен сначала запустить бота.')
        await ads.set_helper(message.from_user.id,int(parts[0]),parts[1]=='on')
        await message.answer('Роль помощника назначена. Пользователь может открыть /admin.' if parts[1]=='on' else 'Роль помощника снята.')
    except ValueError as e:
        await message.answer(escape(str(e)))


@router.callback_query(F.data=='helper_manage')
async def helper_list(call):
    if call.from_user.id not in ADMIN_IDS:
        await answer_safe(call,'Доступ запрещён.',show_alert=True);return
    items=await ads.helpers(call.from_user.id)
    text='<b>Помощник</b>\nНазначить: <code>/helper ID on</code>\nСнять: <code>/helper ID off</code>\n\n'
    text+='\n'.join(f"<code>{u['id']}</code> {escape('@'+u['username'] if u.get('username') else '')}" for u in items[:20]) or 'Помощников пока нет.'
    if len(items)>20:text+='\nПоказаны первые 20. Снять роль можно по ID.'
    await edit_message_safe(call,text,reply_markup=K(inline_keyboard=[[B(text='Назад',callback_data='admin_home')]]));await answer_safe(call)


@router.callback_query(F.data.startswith('advertising:'))
async def advertising_action(call,state):
    if not await ads.is_helper(call.from_user.id):
        await answer_safe(call,'Раздел доступен только помощнику.',show_alert=True);return
    await state.clear()
    parts=call.data.split(':')
    try:
        if parts==['advertising','create']:
            await state.set_state(AdvertisingInput.name)
            await edit_message_safe(call,'Введите название рекламной ссылки (1–80 символов).',reply_markup=K(inline_keyboard=[[B(text='Отмена',callback_data='advertising:list')]]))
        elif parts==['advertising','list'] or (len(parts)==3 and parts[1]=='list' and parts[2].isdigit()):
            items=await ads.campaigns(call.from_user.id)
            rows=[[B(text='Создать рекламную ссылку',callback_data='advertising:create')]]
            page=int(parts[2]) if len(parts)==3 else 0
            rows.extend([B(text=f"{item['name'][:40]} · {item['users_count']}",callback_data=f"advertising:users:{item['id']}:0")] for item in items[page*10:page*10+10])
            nav=[]
            if page:nav.append(B(text='Назад',callback_data=f'advertising:list:{page-1}'))
            if len(items)>page*10+10:nav.append(B(text='Далее',callback_data=f'advertising:list:{page+1}'))
            if nav:rows.append(nav)
            rows.append([B(text='В кабинет',callback_data='admin_home')])
            await edit_message_safe(call,'<b>Реклама</b>\nНовые пользователи по вашим ссылкам. Это не реферальные бонусы.',reply_markup=K(inline_keyboard=rows))
        elif len(parts)==4 and parts[1]=='users' and parts[2].isdigit() and parts[3].isdigit():
            data=await ads.campaign_users(call.from_user.id,int(parts[2]),int(parts[3]))
            if not data:
                raise ValueError('Ссылка не найдена.')
            username=(await call.bot.get_me()).username
            link=f"https://t.me/{username}?start=ad_{data['campaign']['token']}"
            text=f"<b>{escape(data['campaign']['name'])}</b>\n<code>{escape(link)}</code>\n\n"
            text+='\n'.join(f"<code>{u['user_id']}</code> {escape('@'+u['username'] if u.get('username') else 'без username')} · {u['created_at'].replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Europe/Moscow')).strftime('%d.%m.%Y %H:%M')} МСК" for u in data['items']) or 'Новых пользователей пока нет.'
            rows=[];page=int(parts[3]);nav=[]
            if page:nav.append(B(text='Назад',callback_data=f'advertising:users:{parts[2]}:{page-1}'))
            if data['has_more']:nav.append(B(text='Далее',callback_data=f'advertising:users:{parts[2]}:{page+1}'))
            if nav:rows.append(nav)
            rows.append([B(text='Все ссылки',callback_data='advertising:list')])
            await edit_message_safe(call,text,reply_markup=K(inline_keyboard=rows))
        else:
            raise ValueError('Неизвестное действие.')
        await answer_safe(call)
    except (ValueError,PermissionError) as e:
        await answer_safe(call,str(e),show_alert=True)


@router.message(AdvertisingInput.name,F.text,~F.text.startswith('/'))
async def advertising_name(message,state):
    if not await ads.is_helper(message.from_user.id):
        await state.clear();await message.answer('Доступ закрыт.');return
    try:
        campaign=await ads.create_campaign(message.from_user.id,message.text)
    except (ValueError,PermissionError) as e:
        await message.answer(escape(str(e)));return
    await state.clear()
    username=(await message.bot.get_me()).username
    await message.answer(f"<b>{escape(campaign['name'])}</b>\n<code>https://t.me/{username}?start=ad_{campaign['token']}</code>\nУчитываются только новые пользователи. Реферальные бонусы не начисляются.",reply_markup=helper_keyboard())
