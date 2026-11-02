#!/usr/bin/env python3
"""Configure credentials on the VPS terminal and provision a local MariaDB.

No secrets are accepted in command-line arguments or printed in error messages.
Only a database and user owned by this installer may be reused on a retry.
"""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

from dotenv import dotenv_values

STATE_DIR = Path('/etc/session-shope')
DB_NAME = 'session_shope'
DB_USER = 'session_shope_app'


def mysql(sql):
    process = subprocess.run(
        ['mariadb', '--protocol=socket', '--batch', '--skip-column-names'],
        input=sql, text=True, capture_output=True,
    )
    if process.returncode:
        raise ValueError('Не удалось настроить локальную MariaDB. Проверьте systemctl status mariadb.')
    return process.stdout.strip()


def verify_bot(token):
    try:
        request = urllib.request.Request('https://api.telegram.org/bot' + token + '/getMe')
        with urllib.request.urlopen(request, timeout=20, context=ssl.create_default_context()) as result:
            data = json.load(result)
        if not data.get('ok'):
            raise ValueError
    except urllib.error.HTTPError as exc:
        raise ValueError(f'Telegram API вернул HTTP {exc.code}. Проверьте токен бота на сервере.') from None
    except Exception:
        raise ValueError('Не удалось проверить токен через Telegram API. Проверьте токен и доступ сервера к Telegram.') from None


def read_value(prompt, pattern, hidden=False):
    value = (getpass.getpass(prompt) if hidden else input(prompt)).strip()
    if not re.fullmatch(pattern, value):
        raise ValueError('Некорректное значение. Запустите установку повторно и проверьте ввод.')
    return value


def atomic_private(path, contents):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.bootstrap-')
        with os.fdopen(fd, 'w') as stream:
            stream.write(contents)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def configure(project, state_dir=STATE_DIR):
    project = Path(project).resolve()
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    state_dir.chmod(0o700)
    marker = state_dir / 'managed-env'
    env_path = project / '.env'
    resumed = marker.exists()
    if resumed:
        if marker.read_text().strip() != str(project):
            raise ValueError('Сохранённая конфигурация относится к другому каталогу проекта.')
        if not env_path.is_file():
            raise ValueError('Управляемый .env отсутствует. Восстановите его из резервной копии.')
        values = dict(dotenv_values(env_path))
        if values.get('DB_NAME') != DB_NAME or values.get('DB_USER') != DB_USER or values.get('DB_HOST') != '127.0.0.1':
            raise ValueError('Настройки базы изменены вручную. Используйте install.sh без --fresh.')
        password = values.get('DB_PASSWORD', '')
        if not re.fullmatch(r'[0-9a-f]{64}', password):
            raise ValueError('Не удалось прочитать ранее созданный пароль базы. Файл не изменён.')
    else:
        existing = mysql(
            f"SELECT COUNT(*) FROM mysql.user WHERE User = '{DB_USER}';\n"
            f"SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = '{DB_NAME}';"
        )
        if any(line != '0' for line in existing.splitlines()) or len(existing.splitlines()) != 2:
            raise ValueError('Такая база или пользователь уже существуют. Они не изменены. Используйте существующий .env и install.sh без --fresh.')
        print('\nВведите данные прямо в терминале VPS. Токен и API Hash будут скрыты.')
        token = read_value('BOT_TOKEN из BotFather: ', r'[0-9]+:[A-Za-z0-9_-]{20,}', hidden=True)
        verify_bot(token)
        api_id = read_value('TELEGRAM_API_ID (my.telegram.org): ', r'[1-9][0-9]{0,9}')
        api_hash = read_value('TELEGRAM_API_HASH: ', r'[A-Fa-f0-9]{32}', hidden=True)
        admins = read_value('Ваш Telegram ID администратора (или несколько через запятую): ', r'[1-9][0-9]*(,[1-9][0-9]*)*')
        if int(api_id) > 2147483647 or any(int(value) >= 2**63 for value in admins.split(',')):
            raise ValueError('ID выходит за допустимые пределы.')
        password = secrets.token_hex(32)
        values = {
            'BOT_TOKEN': token, 'TELEGRAM_API_ID': api_id, 'TELEGRAM_API_HASH': api_hash,
            'ADMIN_IDS': admins, 'DB_HOST': '127.0.0.1', 'DB_PORT': '3306',
            'DB_USER': DB_USER, 'DB_PASSWORD': password, 'DB_NAME': DB_NAME,
            'MINIAPP_URL': 'https://sbandsub.space', 'MINIAPP_HOST': '127.0.0.1', 'MINIAPP_PORT': '8080',
            'SUPPORT_USERNAME': '', 'CRYPTO_PAY_TOKEN': '', 'XROCKET_API_KEY': '', 'LAVE_PAY_API_KEY': '',
        }
        if env_path.exists():
            backup = state_dir / 'env-before-bootstrap'
            if not backup.exists():
                # Preserve the checkout's existing file privately; never display it.
                atomic_private(backup, env_path.read_text())
        contents = '# Created locally by the Session Shope installer. Keep private.\n'
        contents += ''.join(f"{key}='{value}'\n" for key, value in values.items())
        atomic_private(env_path, contents)
        # Persist ownership before SQL so interrupted provisioning can be retried
        # with the same password, rather than resetting an unrelated account.
        atomic_private(marker, str(project) + '\n')
    if resumed:
        verify_bot(values.get('BOT_TOKEN', ''))
    mysql(
        f'CREATE DATABASE IF NOT EXISTS `{DB_NAME}` COLLATE utf8mb4_unicode_ci;\n'
        + ''.join(
            f"CREATE USER IF NOT EXISTS '{DB_USER}'@'{host}' IDENTIFIED BY '{password}';\n"
            f"ALTER USER '{DB_USER}'@'{host}' IDENTIFIED BY '{password}';\n"
            f"GRANT ALL PRIVILEGES ON `{DB_NAME}`.* TO '{DB_USER}'@'{host}';\n"
            for host in ('localhost', '127.0.0.1')
        )
    )
    print('Локальная база и приватный .env подготовлены. Секреты не выводились.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError('Нужен запуск через sudo.')
    configure(args.project)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as exc:
        print(str(exc) if isinstance(exc, ValueError) else 'Не удалось сохранить конфигурацию на сервере.', file=sys.stderr)
        sys.exit(1)
