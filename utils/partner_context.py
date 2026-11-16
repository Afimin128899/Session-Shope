"""Request-local tenant metadata; never infer a wallet from a client-supplied owner ID."""
from contextvars import ContextVar
CURRENT=ContextVar('partner_context',default=None)
CONTENT=ContextVar('bot_content',default={})


def bot_id():
    value=CURRENT.get()
    return int(value['bot_id']) if value else 0
