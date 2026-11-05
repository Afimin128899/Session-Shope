"""Send only notifications explicitly requested by users."""
import asyncio
import logging
from html import escape
from utils.i18n import tr
from utils.notification_language import recipient_language

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.restock import pending_notifications, claim_notification, finish_notification

logger = logging.getLogger(__name__)


async def send_pending_notifications(bot) -> None:
    for item in await pending_notifications():
        if not await claim_notification(item['token']):
            continue
        try:
            async with recipient_language(item['user_id']):
                await bot.send_message(
                    item['user_id'],
                    tr('🔔 <b>Новое поступление!</b>\n\nВ категории <b>{0}</b> появился товар.\nНаличие и цену можно проверить в магазине.\n\nУведомление отправлено один раз. На следующее поступление можно подписаться снова.', escape(item['name'])),
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text=tr('Открыть магазин'), callback_data='buy'),
                    ]]),
                    parse_mode='HTML',
                )
        except TelegramForbiddenError:
            await finish_notification(item['token'])
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            return
        except Exception:
            logger.exception('Restock notification failed for user %s', item['user_id'])
        else:
            await finish_notification(item['token'])
        await asyncio.sleep(0.05)


async def restock_worker(bot) -> None:
    while True:
        try:
            await send_pending_notifications(bot)
        except Exception:
            logger.exception('Restock notification batch failed')
        await asyncio.sleep(30)
