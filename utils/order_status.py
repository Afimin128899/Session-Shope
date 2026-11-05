"""Shared labels for persistent order and support states."""
from utils.i18n import tr
TICKET_STATUSES = {'open': 'Ждёт поддержки', 'waiting_user': 'Ждёт покупателя', 'closed': 'Закрыт'}


def order_status(order):
    if order.get('status') == 'refunded':
        return tr('Возвращён на баланс')
    if order.get('ticket_status') in {'open', 'waiting_user'}:
        return tr('Проблема · обращение в поддержку')
    if order.get('status') == 'completed' or order.get('completed'):
        return tr('Завершён')
    return tr('Оплачен и выдан')
