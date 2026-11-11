"""Release gates. Enable only after the owner's separate instruction.

Stored URLs, Mini App files and payment configuration remain untouched.
"""
CUSTOMER_MINIAPP_ENABLED = False
ADMIN_MINIAPP_ENABLED = False


async def configure_chat_menu(bot):
    from aiogram.types import MenuButtonCommands, MenuButtonWebApp, WebAppInfo
    from utils.miniapp import customer_miniapp_url
    url = customer_miniapp_url()
    button = MenuButtonWebApp(text='Магазин', web_app=WebAppInfo(url=url)) if url else MenuButtonCommands()
    await bot.set_chat_menu_button(menu_button=button)
