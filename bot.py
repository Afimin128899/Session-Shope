import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from database.db import init_db

from handlers.user.start import start_router
from handlers.user.balance import balance_router
from handlers.user.shop import shop_router
from handlers.user.purchases import purchases_router
from handlers.user.promo import promo_router
from handlers.user.profile import profile_router

from handlers.admin.admin_panel import admin_router
from handlers.admin.manage import manage_router
from handlers.admin.broadcast import broadcast_router
from handlers.admin.add_account import add_account_router
from handlers.admin.button_editor import button_editor_router
from handlers.admin.category_manager import cat_router

from services.cryptobot import crypto_router
from services.tonkeeper import tonkeeper_router
from services.telethon_auth import cleanup_all_clients
from utils.throttling import ThrottlingMiddleware
from middlewares.subscription_middleware import SubscriptionMiddleware
from utils.maintenance import MaintenanceMiddleware


def setup_logging():
    """Настройка логирования: консоль + файл bot.log"""
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Консольный вывод
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    root_logger.addHandler(console_handler)

    # Файловый вывод
    file_handler = logging.FileHandler("bot.log", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    root_logger.addHandler(file_handler)


async def main():
    setup_logging()

    try:
        await init_db()
    except Exception:
        logging.exception(
            "Database initialization failed; polling will not start. "
            "Check DB settings and server IP allowlisting."
        )
        return

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    # Protect the bot from spam and flood abuse
    dp.message.outer_middleware(ThrottlingMiddleware(limit=0.5))
    dp.callback_query.outer_middleware(ThrottlingMiddleware(limit=0.4))

    # Mandatory channel subscription check middleware
    dp.message.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(SubscriptionMiddleware())
    dp.message.outer_middleware(MaintenanceMiddleware())
    dp.callback_query.outer_middleware(MaintenanceMiddleware())

    dp.include_routers(
        start_router, balance_router, shop_router, purchases_router, promo_router, profile_router,
        admin_router, manage_router, broadcast_router, add_account_router, button_editor_router,
        cat_router,
        crypto_router, tonkeeper_router,
    )

    logging.info("Starting bot...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await cleanup_all_clients()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
