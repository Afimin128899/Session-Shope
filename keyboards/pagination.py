from aiogram.types import InlineKeyboardButton


def pagination(page, total, size, prefix):
    pages = max(1, (total + size - 1) // size)
    if pages == 1:
        return []
    row = []
    if page:
        row.append(InlineKeyboardButton(text='←', callback_data=f'{prefix}:{page - 1}'))
    row.append(InlineKeyboardButton(text=f'{page + 1} / {pages}', callback_data='page_info'))
    if page + 1 < pages:
        row.append(InlineKeyboardButton(text='→', callback_data=f'{prefix}:{page + 1}'))
    return [row]
