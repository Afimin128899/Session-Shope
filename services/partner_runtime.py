"""Managed multi-bot polling, isolated request context and restricted partner handlers."""
import asyncio
import json
import logging
import uuid
from io import BytesIO
from pathlib import PurePosixPath
from aiogram import Bot,BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery,Message,PreCheckoutQuery,BufferedInputFile
from database import partners
from database.admin_tools import _transaction
from database.admin_web import rows
from services.partner_tokens import decrypt
from utils.partner_context import CURRENT,CONTENT

MAIN=None
CLIENTS={}
log=logging.getLogger(__name__)
CUSTOMER_MIXED={
 'handlers.direct_support':{'support_command','support','purchase_help','legacy_support','end_support','user_message'},
 'handlers.quality':{'begin_review','submit_review','begin_warranty','submit_warranty','removed_activity','show_reviews'},
 'handlers.navigation':{'cancel','page_info','stale_button','unknown_message'},
}


async def unavailable(event,text):
    if isinstance(event,CallbackQuery):await event.answer(text,show_alert=True)
    elif isinstance(event,PreCheckoutQuery):await event.answer(ok=False,error_message=text[:200])
    elif isinstance(event,Message):await event.answer(text)


class BotScope(BaseMiddleware):
    async def __call__(self,handler,event,data):
        bot=data.get('bot')
        p=await partners.get(bot.id) if MAIN is not None and bot.id!=MAIN.id else None
        if MAIN is not None and bot.id!=MAIN.id and (not p or p['status']!='enabled'):
            return
        if p:p['main_username']=(await MAIN.me()).username
        content=json.loads(p['content_json']) if p else await partners.content(0)
        a=CURRENT.set(p);b=CONTENT.set(content)
        try:
            message=event.message or event.callback_query or event.pre_checkout_query or event.edited_message
            user=getattr(message,'from_user',None)
            if user:
                async with _transaction() as cur:
                    await cur.execute('INSERT INTO user_bot_routes(user_id,bot_id) VALUES(%s,%s) ON DUPLICATE KEY UPDATE bot_id=VALUES(bot_id)',(user.id,p['bot_id'] if p else 0))
                paid=isinstance(message,Message) and bool(message.successful_payment or message.refunded_payment)
                if p and (paid or isinstance(message,PreCheckoutQuery)):
                    if isinstance(message,PreCheckoutQuery):await unavailable(message,'Оплата проводится только через основной бот.')
                    return
                if not paid and await partners.banned(user.id):
                    return await unavailable(message,'Доступ к магазину заблокирован. Обратитесь к владельцу основного бота.')
            return await handler(event,data)
        finally:CONTENT.reset(b);CURRENT.reset(a)


class PartnerPermissions(BaseMiddleware):
    async def __call__(self,handler,event,data):
        p=CURRENT.get()
        if p:
            callback=data['handler'].callback
            module=callback.__module__;name=callback.__name__
            allowed=module.startswith('handlers.user.') or module=='handlers.partners' or name in CUSTOMER_MIXED.get(module,set())
            if not allowed:return await unavailable(event,'Управление магазином доступно только через основной бот.')
            value=(getattr(event,'data',None) or '')
            if value in {'topup_balance','balance','deposit_stars'} or value.startswith(('deposit_','stars_buy:')):
                from handlers.partners import show_funding
                return await show_funding(event,p)
        return await handler(event,data)


async def client_for(user):
    if MAIN is None:return None
    from config import ADMIN_IDS
    if user in ADMIN_IDS:return MAIN
    route=await rows('SELECT bot_id FROM user_bot_routes WHERE user_id=%s',(user,))
    return CLIENTS.get(route[0]['bot_id'],MAIN) if route else MAIN


class RoutingBot:
    def __init__(self,main):self.main=main
    def __getattr__(self,key):return getattr(self.main,key)
    async def send_message(self,chat_id,*args,**kwargs):
        client=await client_for(int(chat_id)) if str(chat_id).lstrip('-').isdigit() else self.main
        return await (client or self.main).send_message(chat_id,*args,**kwargs)


async def copy_between(message,destination,target):
    if destination is message.bot or destination.id==message.bot.id:
        return await destination.copy_message(chat_id=target,from_chat_id=message.chat.id,message_id=message.message_id)
    kind=getattr(message.content_type,'value',message.content_type)
    if kind=='text':return await destination.send_message(target,message.text,entities=message.entities,parse_mode=None)
    if kind=='contact':
        c=message.contact;return await destination.send_contact(target,c.phone_number,c.first_name,last_name=c.last_name,vcard=c.vcard)
    if kind=='location':return await destination.send_location(target,message.location.latitude,message.location.longitude)
    media=message.photo[-1] if kind=='photo' else getattr(message,kind,None)
    if not media or (media.file_size or 0)>20*1024*1024:raise ValueError('Вложение для межботовой доставки должно быть до 20 МБ.')
    file=await message.bot.get_file(media.file_id)
    if (file.file_size or 0)>20*1024*1024:raise ValueError('Слишком большое вложение.')
    data=BytesIO();await message.bot.download_file(file.file_path,destination=data)
    if data.tell()>20*1024*1024:raise ValueError('Слишком большое вложение.')
    upload=BufferedInputFile(data.getvalue(),filename=PurePosixPath(file.file_path).name)
    fields={kind:upload}
    if kind not in {'sticker','video_note'}:fields.update(caption=message.caption,caption_entities=message.caption_entities,parse_mode=None)
    return await getattr(destination,'send_'+kind)(chat_id=target,**fields)


async def claim(identity,lease):
    async with _transaction() as cur:
        await cur.execute("UPDATE partner_bots SET lease_owner=%s,lease_until=DATE_ADD(UTC_TIMESTAMP(),INTERVAL 70 SECOND) WHERE bot_id=%s AND status='enabled' AND (lease_owner=%s OR lease_until IS NULL OR lease_until<UTC_TIMESTAMP())",(lease,identity,lease))
        if cur.rowcount:return True
        # MySQL reports zero changed rows when renewing twice in one second.
        await cur.execute("SELECT lease_owner,status,lease_until>=UTC_TIMESTAMP() AS valid FROM partner_bots WHERE bot_id=%s",(identity,));row=await cur.fetchone()
        return bool(row and row['lease_owner']==lease and row['status']=='enabled' and row['valid'])


async def poll(dp,p,lease):
    if not await claim(p['bot_id'],lease):return
    bot=None
    try:
        bot=Bot(decrypt(p['token_cipher']),default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        if bot.id!=p['bot_id']:raise ValueError('Partner identity mismatch')
        from utils.button_icons import MissingButtonIcons
        bot.session.middleware(MissingButtonIcons())
        await bot.delete_webhook(drop_pending_updates=False)
        CLIENTS[bot.id]=bot;offset=p['offset_id']
        while await claim(bot.id,lease):
            updates=await bot.get_updates(offset=offset,timeout=20,allowed_updates=dp.resolve_used_update_types())
            for update in updates:
                current=await partners.get(bot.id)
                if not current or current['status']!='enabled' or current['lease_owner']!=lease:return
                try:await dp.feed_update(bot,update)
                except Exception as exc:log.warning('Partner update failed [%s], bot=%s',type(exc).__name__,bot.id)
                offset=update.update_id+1
                async with _transaction() as cur:
                    await cur.execute('UPDATE partner_bots SET offset_id=%s WHERE bot_id=%s AND lease_owner=%s',(offset,bot.id,lease))
    except asyncio.CancelledError:raise
    except Exception as exc:log.warning('Partner polling unavailable [%s], bot=%s',type(exc).__name__,p['bot_id'])
    finally:
        CLIENTS.pop(p['bot_id'],None)
        if bot:await bot.session.close()
        async with _transaction() as cur:
            await cur.execute('UPDATE partner_bots SET lease_owner=NULL,lease_until=NULL WHERE bot_id=%s AND lease_owner=%s',(p['bot_id'],lease))


async def manager(dp,main):
    global MAIN
    MAIN=main;tasks={};lease=uuid.uuid4().hex
    try:
        while True:
            try:enabled=await rows("SELECT * FROM partner_bots WHERE status='enabled'")
            except Exception as exc:
                log.warning('Partner registry unavailable [%s]',type(exc).__name__);await asyncio.sleep(5);continue
            ids={p['bot_id'] for p in enabled}
            for identity,task in list(tasks.items()):
                if identity not in ids:task.cancel();await asyncio.gather(task,return_exceptions=True);tasks.pop(identity)
            for p in enabled:
                if p['bot_id'] not in tasks or tasks[p['bot_id']].done():
                    previous=tasks.get(p['bot_id'])
                    if previous:await asyncio.gather(previous,return_exceptions=True)
                    tasks[p['bot_id']]=asyncio.create_task(poll(dp,p,lease))
            await asyncio.sleep(5)
    finally:
        for task in tasks.values():task.cancel()
        await asyncio.gather(*tasks.values(),return_exceptions=True)
        MAIN=None
