from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import StateFilter

from config import ADMIN_IDS
from database.db import (
    get_all_categories, get_category, create_category,
    update_category, update_category_emoji, toggle_category, delete_category,
    get_accounts_by_country, update_account_country,
)
from handlers.admin.add_account import AddAccountState
from keyboards.admin_kb import back_to_admin
from utils.nav import edit_message_safe, answer_safe
from utils.emoji_map import EMOJI_PHONE

cat_router = Router()


class CategoryState(StatesGroup):
    waiting_name = State()
    waiting_emoji = State()
    waiting_edit_name = State()
    waiting_edit_emoji = State()


RUSSIAN_TO_LATIN = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
}


def slugify(text: str) -> str:
    text = text.lower().strip()
    result = []
    for ch in text:
        if ch in RUSSIAN_TO_LATIN:
            result.append(RUSSIAN_TO_LATIN[ch])
        elif ch.isalnum() or ch in '-_':
            result.append(ch)
        elif ch == ' ':
            result.append('_')
    return ''.join(result)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


@cat_router.callback_query(F.data == "admin_categories")
async def categories_list(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.clear()

    cats = await get_all_categories()
    if not cats:
        text = "📂 <b>Категории</b>\n\nКатегорий пока нет."
        rows = [
            [InlineKeyboardButton(text="➕ Создать категорию", callback_data="cat_create")],
            [InlineKeyboardButton(text="« Назад", callback_data="admin_home")],
        ]
        await edit_message_safe(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await answer_safe(call)
        return

    text = "📂 <b>Управление категориями</b>"
    rows = []
    for c in cats:
        active = "✅" if c["is_active"] else "❌"
        emoji = c.get("emoji")
        if emoji and emoji.isdigit():
            rows.append([
                InlineKeyboardButton(
                    text=f"{c['name']} {active}",
                    callback_data=f"cat_detail:{c['slug']}",
                    icon_custom_emoji_id=emoji,
                )
            ])
        else:
            display_emoji = emoji or "📁"
            rows.append([
                InlineKeyboardButton(
                    text=f"{display_emoji} {c['name']} {active}",
                    callback_data=f"cat_detail:{c['slug']}",
                )
            ])
    rows.append([InlineKeyboardButton(text="➕ Создать", callback_data="cat_create")])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_home")])

    await edit_message_safe(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)


@cat_router.callback_query(F.data.startswith("cat_detail:"))
async def category_detail(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    slug = call.data.split(":", 1)[1]
    cat = await get_category(slug)
    if not cat:
        await answer_safe(call, "❌ Категория не найдена", show_alert=True)
        return

    active = "✅ Включена" if cat["is_active"] else "❌ Отключена"
    raw_emoji = cat.get("emoji")
    if raw_emoji and raw_emoji.isdigit():
        emoji_display = f'<tg-emoji emoji-id="{raw_emoji}">📁</tg-emoji>'
    elif raw_emoji:
        emoji_display = raw_emoji
    else:
        emoji_display = "—"
    accounts = await get_accounts_by_country(slug)
    available = len(accounts)

    text = (
        f"📂 <b>Категория:</b> {emoji_display} {cat['name']}\n\n"
        f"<b>Статус:</b> {active}\n"
        f"<b>Аккаунтов в наличии:</b> {available}\n"
    )

    rows = [
        [InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data=f"cat_add_acc:{slug}")],
        [InlineKeyboardButton(text="✏️ Изменить название", callback_data=f"cat_edit_name:{slug}")],
        [InlineKeyboardButton(text="🎭 Изменить эмодзи", callback_data=f"cat_edit_emoji:{slug}")],
        [InlineKeyboardButton(text="🔄 Вкл/Выкл", callback_data=f"cat_toggle:{slug}")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"cat_delete:{slug}")],
        [InlineKeyboardButton(text="« К списку", callback_data="admin_categories")],
    ]
    await edit_message_safe(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)


@cat_router.callback_query(F.data.startswith("cat_toggle:"))
async def category_toggle(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    slug = call.data.split(":", 1)[1]
    await toggle_category(slug)
    await answer_safe(call, "✅ Статус изменён", show_alert=True)
    await category_detail(call)


@cat_router.callback_query(F.data.startswith("cat_delete:"))
async def category_delete(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    slug = call.data.split(":", 1)[1]
    await delete_category(slug)
    await answer_safe(call, "✅ Категория удалена", show_alert=True)
    await categories_list(call, state)


@cat_router.callback_query(F.data.startswith("cat_add_acc:"))
async def category_add_account(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    slug = call.data.split(":", 1)[1]
    await state.update_data(password="-", category_slug=slug)
    await state.set_state(AddAccountState.waiting_for_phone)
    await edit_message_safe(
        call,
        f"<tg-emoji emoji-id='{EMOJI_PHONE}'>📞</tg-emoji> <b>Добавление аккаунта</b>\n\n"
        "Отправьте номер телефона в международном формате:\n"
        "<blockquote>+79991234567</blockquote>",
        reply_markup=back_to_admin(),
    )
    await answer_safe(call)


@cat_router.callback_query(F.data == "cat_create")
async def category_create_name(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(CategoryState.waiting_name)
    await edit_message_safe(
        call,
        "➕ <b>Создание категории</b>\n\n"
        "Введите <b>название</b> категории:\n"
        "Пример: <code>Казахстан</code>\n\n"
        "<i>Slug создастся автоматически.</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="« Отмена", callback_data="admin_categories")],
        ]),
    )
    await answer_safe(call)


@cat_router.message(StateFilter(CategoryState.waiting_name), F.text)
async def category_create_name_process(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    name = message.text.strip()
    if len(name) < 1:
        await message.answer("❌ Название не может быть пустым.")
        return

    slug = slugify(name)
    await state.update_data(cat_name=name, cat_slug=slug)
    await state.set_state(CategoryState.waiting_emoji)
    await message.answer(
        f"Название: <b>{name}</b>\n"
        f"Slug: <code>{slug}</code>\n\n"
        "Отправьте <b>эмодзи</b> для категории (или <code>-</code> чтобы пропустить):"
    )


@cat_router.message(StateFilter(CategoryState.waiting_emoji))
async def category_create_emoji_process(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    emoji = None
    if message.entities:
        for entity in message.entities:
            if entity.type == "custom_emoji":
                emoji = str(entity.custom_emoji_id)
                break

    if not emoji and message.text:
        text = message.text.strip()
        if text != "-":
            emoji = text

    data = await state.get_data()
    slug = data.get("cat_slug")
    name = data.get("cat_name")

    ok = await create_category(slug, name, emoji)
    await state.clear()

    if ok:
        emoji_display = ""
        if emoji:
            if emoji.isdigit():
                emoji_display = f'<tg-emoji emoji-id="{emoji}">📁</tg-emoji> '
            else:
                emoji_display = f"{emoji} "
        await message.answer(
            f"✅ Категория <b>{emoji_display}{name}</b> создана!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="« К категориям", callback_data="admin_categories")],
            ]),
        )
    else:
        await message.answer(
            f"❌ Ошибка: категория с slug <code>{slug}</code> уже существует.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="« К категориям", callback_data="admin_categories")],
            ]),
        )


@cat_router.callback_query(F.data.startswith("cat_edit_name:"))
async def category_edit_name(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    slug = call.data.split(":", 1)[1]
    await state.update_data(edit_slug=slug)
    await state.set_state(CategoryState.waiting_edit_name)
    await edit_message_safe(
        call,
        f"Введите новое название для категории:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="« Отмена", callback_data=f"cat_detail:{slug}")],
        ]),
    )
    await answer_safe(call)


@cat_router.message(StateFilter(CategoryState.waiting_edit_name), F.text)
async def category_edit_name_process(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    name = message.text.strip()
    data = await state.get_data()
    slug = data.get("edit_slug")
    cat = await get_category(slug)
    if not cat:
        await state.clear()
        await message.answer("❌ Категория не найдена")
        return

    await update_category(slug, name, cat.get("emoji"))
    await state.clear()
    await message.answer(
        f"✅ Название изменено на <b>{name}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="« К категории", callback_data=f"cat_detail:{slug}")],
        ]),
    )


@cat_router.callback_query(F.data.startswith("cat_edit_emoji:"))
async def category_edit_emoji(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    slug = call.data.split(":", 1)[1]
    await state.update_data(edit_slug=slug)
    await state.set_state(CategoryState.waiting_edit_emoji)
    await edit_message_safe(
        call,
        f"Отправьте новый эмодзи для категории\n(или <code>-</code> чтобы очистить):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="« Отмена", callback_data=f"cat_detail:{slug}")],
        ]),
    )
    await answer_safe(call)


@cat_router.message(StateFilter(CategoryState.waiting_edit_emoji))
async def category_edit_emoji_process(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    emoji = None
    if message.entities:
        for entity in message.entities:
            if entity.type == "custom_emoji":
                emoji = str(entity.custom_emoji_id)
                break

    if not emoji and message.text:
        text = message.text.strip()
        if text != "-":
            emoji = text

    data = await state.get_data()
    slug = data.get("edit_slug")
    cat = await get_category(slug)
    if not cat:
        await state.clear()
        await message.answer("❌ Категория не найдена")
        return

    ok = await update_category_emoji(slug, emoji)
    await state.clear()
    if ok:
        emoji_display = ""
        if emoji:
            if emoji.isdigit():
                emoji_display = f'<tg-emoji emoji-id="{emoji}">📁</tg-emoji> '
            else:
                emoji_display = f"{emoji} "
        await message.answer(
            f"✅ Эмодзи для <b>{emoji_display}{cat['name']}</b> обновлено!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="« К категории", callback_data=f"cat_detail:{slug}")],
            ]),
        )
    else:
        await message.answer(
            f"❌ Ошибка: эмодзи не обновлено (slug <code>{slug}</code> не найден).",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="« К категории", callback_data=f"cat_detail:{slug}")],
            ]),
        )
