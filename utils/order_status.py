"""Shared labels for persistent order and support states."""
TICKET_STATUSES = {'open': 'Ждёт поддержки', 'waiting_user': 'Ждёт покупателя', 'closed': 'Закрыт'}


def order_status(order):
    if order.get('status') == 'refunded':
        return 'Возвращён на баланс'
    if order.get('ticket_status') in {'open', 'waiting_user'}:
        return 'Проблема · обращение в поддержку'
    if order.get('status') == 'completed' or order.get('completed'):
        return 'Завершён'
    return 'Оплачен и выдан'
