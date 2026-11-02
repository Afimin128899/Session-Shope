"""Build a Telegram support draft containing only the order reference."""
import re
from urllib.parse import urlencode, urlsplit


def purchase_support_url(contact: str, purchase_id: int) -> str | None:
    contact = contact.strip()
    if contact.startswith(('https://', 'http://', 't.me/')):
        parsed = urlsplit(contact if '://' in contact else 'https://' + contact)
        if parsed.hostname not in {'t.me', 'telegram.me'}:
            return None
        contact = parsed.path.strip('/')
    username = contact.lstrip('@')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{4,31}', username):
        return None
    return f'https://t.me/{username}?' + urlencode({
        'text': f'Здравствуйте! Есть проблема с заказом #{purchase_id}.\nОписание проблемы: ',
    })
