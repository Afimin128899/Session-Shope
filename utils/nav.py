from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest

from database.db import create_user, get_user
from keyboards.user_kb import main_menu
from utils import constants as c
from utils.emoji_map import EMOJI_WALLET, EMOJI_BACK, EMOJI_CYCLE


async def ensure_user(user_id: int, username: str | None = None) -> None:
    await create_user(user_id, username)


async def answer_safe(call: CallbackQuery, *args, **kwargs) -> None:
    try:
        await call.answer(*args, **kwargs)
    except TelegramBadRequest as e:
        err_msg = str(e).lower()
        if "query is too old" in err_msg or "query id is invalid" in err_msg:
            pass
        else:
            print(f"[nav.py] Ошибка call.answer: {e}")
    except Exception:
        pass


async def edit_message_safe(call: CallbackQuery, text: str, reply_markup=None, parse_mode: str = "HTML") -> None:
    try:
        if call.message and call.message.photo:
            try:
                await call.message.delete()
            except Exception:
                pass
            await call.message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
            return
        await call.message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest as e:
        err_msg = str(e).lower()
        if "message is not modified" in err_msg:
            pass
        else:
            try:
                await call.message.delete()
            except Exception:
                pass
            await call.message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        print(f"[nav.py] Ошибка edit_message_safe: {e}")
        await call.message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)


async def edit_main(call: CallbackQuery) -> None:
    await ensure_user(call.from_user.id, call.from_user.username)
    caption_text = (
        f"<tg-emoji emoji-id=\"5258362837411045098\">👤</tg-emoji> <b>Главное меню магазина</b>\n\n"
        f"<i>Воспользуйтесь меню ниже для выбора категории или пополнения баланса.</i>"
    )
    await edit_message_safe(call, caption_text, reply_markup=await main_menu(call.from_user.id))


async def edit_balance(call: CallbackQuery, currency: str = "USDT") -> None:
    await ensure_user(call.from_user.id, call.from_user.username)
    user = await get_user(call.from_user.id)
    balance = float(user["balance"]) if user and "balance" in user else 0.0

    text = (
        f"<tg-emoji emoji-id=\"5258260149037965799\">💼</tg-emoji> <b>Мой кошелёк</b>\n\n"
        f"<tg-emoji emoji-id=\"5406841020769936275\">💵</tg-emoji> <b>Баланс:</b> <code>{balance:.2f} ₽</code>\n\n"
        f"Выберите способ пополнения баланса ниже <tg-emoji emoji-id=\"5470177992950946662\">👇</tg-emoji>"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Пополнить баланс",
                callback_data="topup_balance",
                icon_custom_emoji_id=EMOJI_WALLET
            )
        ],
        [
            InlineKeyboardButton(
                text="Назад",
                callback_data="main_menu",
                icon_custom_emoji_id=EMOJI_BACK
            )
        ],
    ])

    await edit_message_safe(call, text, reply_markup=kb)
