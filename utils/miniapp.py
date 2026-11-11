"""Optional public Mini App URL, configured only after HTTPS deployment."""
import os
from urllib.parse import urlsplit


def miniapp_url():
    value = os.getenv('MINIAPP_URL', '').strip()
    if not value:
        return None
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in {'', '/'}):
        raise ValueError('MINIAPP_URL должен быть HTTPS-адресом корня сайта, например https://sbandsub.space')
    return value.rstrip('/')


def customer_miniapp_url():
    from utils.app_access import CUSTOMER_MINIAPP_ENABLED
    return miniapp_url() if CUSTOMER_MINIAPP_ENABLED else None


def admin_miniapp_url():
    from utils.app_access import ADMIN_MINIAPP_ENABLED
    url = miniapp_url() if ADMIN_MINIAPP_ENABLED else None
    return url + '/admin-app' if url else None
