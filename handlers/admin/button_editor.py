from utils.i18n import tr
from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_IDS
from database.db import get_button_label, set_button_label, set_button_emoji, get_all_button_labels
from utils.nav import edit_message_safe, answer_safe

button_editor_router = Router()

BUTTON_CATEGORIES = {
    "main_menu": {
        "title": "Главное меню",
        "keys": [
            "btn_balance", "btn_buy", "btn_purchases",
            "btn_support", "btn_reviews", "btn_promo", "btn_info",
            "btn_profile", "btn_admin_panel",
        ],
    },
    "profile": {
        "title": "Профиль / Рефералка",
        "keys": ["btn_referral_system", "btn_back_profile"],
    },
    "shop": {
        "title": "Аккаунты (кнопки)",
        "keys": [
            "btn_back_shop", "btn_buy_confirm", "btn_cancel",
        ],
    },
    "purchases": {
        "title": "Покупки",
        "keys": ["btn_get_code", "btn_back_purchases", "btn_complete_purchase"],
    },
    "promo": {
        "title": "Промокод",
        "keys": ["btn_promo_cancel"],
    },
}

EDITABLE_KEYS = []
for cat in BUTTON_CATEGORIES.values():
    EDITABLE_KEYS.extend(cat["keys"])

DEFAULT_LABELS = {
    "btn_balance": "Баланс и пополнить",
    "btn_buy": "Купить Аккаунт",
    "btn_purchases": "Мои покупки",
    "btn_support": "Поддержка",
    "btn_reviews": "Отзывы",
    "btn_promo": "Ввести промокод",
    "btn_info": "Информация",
    "btn_profile": "Мой профиль",
    "btn_admin_panel": "Админ-панель",
    "btn_referral_system": "Реферальная система",
    "btn_back_profile": "« Назад",
    "btn_back_shop": "Назад",
    "btn_buy_confirm": "Купить — {price:.4f} TON",
    "btn_cancel": "Отмена",
    "btn_get_code": "Получить код",
    "btn_back_purchases": "Назад",
    "btn_complete_purchase": "Завершение покупки",
    "btn_promo_cancel": "Назад",
}


class ButtonEditorState(StatesGroup):
    choosing_button = State()
    entering_label = State()
    setting_emoji = State()
    waiting_welcome_photo = State()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


@button_editor_router.callback_query(F.data == "admin_btn_editor")
async def btn_editor_categories(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await answer_safe(call)
        return
    await state.clear()
    cats = [('main_menu', tr('🏠 Главное меню')), ('profile', tr('👤 Профиль')), ('shop', tr('🏪 Аккаунты')), ('purchases', tr('📋 Покупки')), ('promo', tr('🎟 Промокод'))]
    rows = [[InlineKeyboardButton(text=title, callback_data=f'btn_cat:{cat_id}')] for cat_id, title in cats]
    rows.append([InlineKeyboardButton(text=tr('🖼 Изменить фото меню'), callback_data='btn_edit_welcome_photo')])
    rows.append([InlineKeyboardButton(text=tr('« Назад'), callback_data='admin_home')])
    await edit_message_safe(call, tr('<b>Редактор кнопок</b>\n\nВыберите раздел для редактирования:'), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)


@button_editor_router.callback_query(F.data.startswith("btn_cat:"))
async def btn_editor_list(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await answer_safe(call)
        return
    cat_id = call.data.split(':', 1)[1]
    cat = BUTTON_CATEGORIES.get(cat_id)
    if not cat:
        await answer_safe(call, tr('Раздел не найден'), show_alert=True)
        return
    await state.update_data(btn_cat=cat_id)
    db_labels = await get_all_button_labels()
    db_map = {r['btn_key']: r for r in db_labels} if db_labels else {}
    text = tr('<b>Редактор кнопок</b> — {0}\n\nВыберите кнопку:\n', f"{cat['title']}")
    rows = []
    for key in cat['keys']:
        db_row = db_map.get(key)
        if db_row and db_row.get('label'):
            current_label = db_row['label']
            source = tr('✨ кастом')
        else:
            current_label = tr(DEFAULT_LABELS.get(key, key))
            source = tr('⚙️ дефолт')
        emoji_indicator = ' 🎭' if db_row and db_row.get('emoji_id') else ''
        rows.append([InlineKeyboardButton(text=f'{current_label[:20]} [{source}{emoji_indicator}]', callback_data=f'btn_edit:{key}')])
    rows.append([InlineKeyboardButton(text=tr('« К разделам'), callback_data='admin_btn_editor')])
    await edit_message_safe(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)


@button_editor_router.callback_query(F.data.startswith("btn_edit:"))
async def btn_edit_action(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    key = call.data.split(':', 1)[1]
    await state.update_data(editing_key=key)
    db_row = await get_button_label(key)
    current_label = db_row['label'] if db_row and db_row.get('label') else tr(DEFAULT_LABELS.get(key, key))
    text = tr('<b>Редактирование:</b> <code>{0}</code>\n\nТекущий текст: <b>{1}</b>\n\nВыберите действие:', f'{key}', f'{current_label}')
    rows = [[InlineKeyboardButton(text=tr('Изменить текст'), callback_data=f'btn_set_label:{key}')], [InlineKeyboardButton(text=tr('Установить эмодзи'), callback_data=f'btn_set_emoji:{key}')], [InlineKeyboardButton(text=tr('Очистить эмодзи'), callback_data=f'btn_clear_emoji:{key}')], [InlineKeyboardButton(text=tr('« Назад'), callback_data='admin_btn_editor')]]
    await edit_message_safe(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)


@button_editor_router.callback_query(F.data.startswith("btn_set_label:"))
async def btn_start_set_label(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    key = call.data.split(':', 1)[1]
    await state.update_data(editing_key=key)
    await state.set_state(ButtonEditorState.entering_label)
    await edit_message_safe(call, tr('Введите новый текст для кнопки <code>{0}</code>\n(от 1 до 64 символов):', f'{key}'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('« Отмена'), callback_data=f'btn_edit:{key}')]]))
    await answer_safe(call)


@button_editor_router.message(StateFilter(ButtonEditorState.entering_label), F.text)
async def btn_process_label(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    key = data.get('editing_key')
    label = message.text.strip()
    if len(label) < 1 or len(label) > 64:
        await message.answer(tr('❌ Текст должен быть от 1 до 64 символов. Попробуйте ещё раз:'))
        return
    await set_button_label(key, label)
    await state.clear()
    cat_id = data.get('btn_cat')
    back_data = f'btn_cat:{cat_id}' if cat_id else 'admin_btn_editor'
    await message.answer(tr('✅ Текст кнопки <code>{0}</code> изменён на «{1}»', f'{key}', f'{label}'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('« В редактор'), callback_data=back_data)]]))


@button_editor_router.callback_query(F.data.startswith("btn_set_emoji:"))
async def btn_start_set_emoji(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    key = call.data.split(':', 1)[1]
    await state.update_data(editing_key=key)
    await state.set_state(ButtonEditorState.setting_emoji)
    await edit_message_safe(call, tr('Отправьте кастомный эмодзи для кнопки <code>{0}</code>\n\n<i>Используйте стикер-панель Telegram для выбора кастомного эмодзи.</i>', f'{key}'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('« Отмена'), callback_data=f'btn_edit:{key}')]]))
    await answer_safe(call)


@button_editor_router.message(StateFilter(ButtonEditorState.setting_emoji))
async def btn_process_emoji(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    key = data.get('editing_key')
    if not message.entities:
        await message.answer(tr('❌ Сообщение не содержит кастомного эмодзи. Отправьте именно кастомный эмодзи:'))
        return
    emoji_id = None
    for entity in message.entities:
        if entity.type == 'custom_emoji':
            emoji_id = str(entity.custom_emoji_id)
            break
    if not emoji_id:
        await message.answer(tr('❌ Не найден кастомный эмодзи. Отправьте именно кастомный эмодзи:'))
        return
    await set_button_emoji(key, emoji_id)
    await state.clear()
    cat_id = data.get('btn_cat')
    back_data = f'btn_cat:{cat_id}' if cat_id else 'admin_btn_editor'
    await message.answer(tr('✅ Эмодзи для кнопки <code>{0}</code> установлено!', f'{key}'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('« В редактор'), callback_data=back_data)]]))


@button_editor_router.callback_query(F.data.startswith("btn_clear_emoji:"))
async def btn_clear_emoji(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    key = call.data.split(':', 1)[1]
    await set_button_emoji(key, None)
    await state.clear()
    await answer_safe(call, tr('✅ Эмодзи очищено!'), show_alert=True)
    db_row = await get_button_label(key)
    current_label = db_row['label'] if db_row and db_row.get('label') else tr(DEFAULT_LABELS.get(key, key))
    text = tr('<b>Редактирование:</b> <code>{0}</code>\n\nТекущий текст: <b>{1}</b>\n\nВыберите действие:', f'{key}', f'{current_label}')
    rows = [[InlineKeyboardButton(text=tr('Изменить текст'), callback_data=f'btn_set_label:{key}')], [InlineKeyboardButton(text=tr('Установить эмодзи'), callback_data=f'btn_set_emoji:{key}')], [InlineKeyboardButton(text=tr('Очистить эмодзи'), callback_data=f'btn_clear_emoji:{key}')], [InlineKeyboardButton(text=tr('« Назад'), callback_data='admin_btn_editor')]]
    await edit_message_safe(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@button_editor_router.callback_query(F.data == "btn_edit_welcome_photo")
async def btn_edit_welcome_photo(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await answer_safe(call)
        return
    await state.set_state(ButtonEditorState.waiting_welcome_photo)
    await edit_message_safe(call, tr('<b>Изменение фото главного меню</b>\n\nОтправьте изображение в формате PNG/JPG.\nОно будет отображаться на приветственном экране главного меню.'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('« Отмена'), callback_data='admin_btn_editor')]]))
    await answer_safe(call)


@button_editor_router.message(StateFilter(ButtonEditorState.waiting_welcome_photo), F.photo)
async def btn_process_welcome_photo(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    import os
    os.makedirs('assets', exist_ok=True)
    photo = message.photo[-1]
    await message.bot.download(photo, destination='assets/welcome.png')
    await state.clear()
    await message.answer(tr('✅ Фото главного меню успешно обновлено!'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('« В редактор'), callback_data='admin_btn_editor')]]))


@button_editor_router.message(StateFilter(ButtonEditorState.waiting_welcome_photo))
async def btn_process_welcome_photo_invalid(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(tr('❌ Пожалуйста, отправьте именно <b>фотографию</b>.\nЕсли хотите отменить, нажмите кнопку под предыдущим сообщением.'))
