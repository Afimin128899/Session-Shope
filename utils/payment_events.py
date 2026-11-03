from aiogram.types import Message

def is_payment_event(event):
    return isinstance(event,Message) and bool(event.successful_payment or event.refunded_payment)
