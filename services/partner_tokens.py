"""Bot tokens are encrypted at rest and are never included in application logs/UI."""
import os
from cryptography.fernet import Fernet,InvalidToken


def cipher():
    key=os.getenv('PARTNER_BOT_KEY','').strip()
    if not key:raise ValueError('Подключение партнёрских ботов пока не настроено владельцем.')
    try:return Fernet(key.encode('ascii'))
    except (ValueError,UnicodeError):raise ValueError('Некорректный ключ хранилища партнёрских ботов.') from None


def encrypt(token):return cipher().encrypt(token.encode())


def decrypt(value):
    try:return cipher().decrypt(bytes(value)).decode()
    except (InvalidToken,UnicodeError):raise ValueError('Не удалось открыть токен партнёра. Проверьте ключ хранилища.') from None
