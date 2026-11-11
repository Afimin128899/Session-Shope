from utils.i18n import tr
import logging
from html import escape
from aiogram import Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_IDS
from utils.nav import edit_message_safe, answer_safe
from utils.emoji_map import EMOJI_MEGA, EMOJI_CHECK, EMOJI_PIN, EMOJI_EXCLAMATION


async def is_user_subscribed(bot: Bot, user_id: int) -> bool:
    """Проверяет подписку пользователя на обязательный канал."""
    if user_id in ADMIN_IDS:
        return True

    from database.db import get_subscription_settings
    settings = await get_subscription_settings()
    if not settings["enabled"] or not settings["channel_id"]:
        return True

    channel_id = settings["channel_id"]
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        if member.status in ["creator", "administrator", "member"]:
            return True
        if member.status == 'restricted' and getattr(member, 'is_member', False):
            return True
        return False
    except Exception as e:
        logging.warning('Subscription check unavailable: %s', type(e).__name__)
        # Если возникла ошибка API или бот не админ, не блокируем пользователя при технических сбоях
        return True


async def send_sub_prompt(event: CallbackQuery | Message, bot: Bot):
    """Отправляет или обновляет сообщение с требованием подписаться на канал."""
    from database.db import get_subscription_settings
    settings = await get_subscription_settings()
    url = settings.get('channel_url')
    if not url:
        ch = settings.get('channel_id', '').lstrip('@')
        url = f'https://t.me/{ch}'
    text = tr("<tg-emoji emoji-id='{0}'>📢</tg-emoji> <b>Обязательная подписка</b>\n\nДля доступа к боту необходимо подписаться на наш официальный канал!\n\n<blockquote><tg-emoji emoji-id='{1}'>📍</tg-emoji> <b>Ссылка на наш канал:</b>\n{2}</blockquote>\n\n<i>После подписки нажмите кнопку <b>«<tg-emoji emoji-id='{3}'>✅</tg-emoji> Я подписался»</b> ниже 👇</i>", f'{EMOJI_MEGA}', f'{EMOJI_PIN}', f'{escape(url)}', f'{EMOJI_CHECK}')
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('Подписаться на канал'), url=url, icon_custom_emoji_id=EMOJI_MEGA)], [InlineKeyboardButton(text=tr('Я подписался'), callback_data='check_sub_status', icon_custom_emoji_id=EMOJI_CHECK)]])
    from utils.legal import information_button
    kb.inline_keyboard.append([information_button()])
    kb.inline_keyboard.append([InlineKeyboardButton(text=tr('Написать в поддержку'), callback_data='support')])
    if isinstance(event, CallbackQuery):
        await edit_message_safe(event, text, reply_markup=kb)
        await answer_safe(event)
    elif isinstance(event, Message):
        await event.answer(text, reply_markup=kb)
