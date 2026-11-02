#!/usr/bin/env python3
"""Create or update the existing bot's systemd service on the VPS.

Run from the uploaded checkout: sudo python3 deploy/create_service.py
No passwords or tokens are copied into the generated unit.
"""
import argparse
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def unit_quote(value):
    if '\n' in value or '\r' in value or '\x00' in value:
        raise ValueError('Недопустимый путь.')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def discover_service(root):
    units = run('systemctl', 'list-unit-files', '--type=service', '--no-legend', '--no-pager')
    found = []
    for line in units.splitlines():
        name = line.split()[0]
        if not name.endswith('.service'):
            continue
        command = run('systemctl', 'show', name, '--property=ExecStart', '--value')
        directory = run('systemctl', 'show', name, '--property=WorkingDirectory', '--value')
        if str(root / 'bot.py') in command or (directory == str(root) and re.search(r'\bbot\.py\b', command)):
            found.append(name)
    if len(found) > 1:
        raise ValueError('Найдено несколько сервисов бота. Укажите нужный через --service NAME.service.')
    return found[0] if found else None


def render_unit(root, python, username):
    return f'''[Unit]
Description=Session Shope bot and Mini App
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User={username}
WorkingDirectory={str(root).replace('%', '%%')}
ExecStart={unit_quote(str(python))} {unit_quote(str(root / 'bot.py'))}
Environment="PYTHONUNBUFFERED=1"
Environment="MINIAPP_URL=https://sbandsub.space"
Environment="MINIAPP_HOST=127.0.0.1"
Environment="MINIAPP_PORT=8080"
Restart=on-failure
RestartSec=5
TimeoutStopSec=45

[Install]
WantedBy=multi-user.target
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service', help='Existing service name, for example shop.service')
    parser.add_argument('--python', type=Path, help='Python from the installed project virtual environment')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError('Запустите через sudo python3 deploy/create_service.py')
    if not (ROOT / 'bot.py').is_file() or not (ROOT / 'miniapp' / 'server.py').is_file():
        raise ValueError('Сначала загрузите полную версию 3.0.0 в каталог проекта.')
    if args.service and not re.fullmatch(r'[A-Za-z0-9_.@-]+\.service', args.service):
        raise ValueError('Укажите имя вида shop.service без пути.')
    existing = args.service or discover_service(ROOT)
    name = existing or 'session-shope.service'
    if existing:
        if run('systemctl', 'show', name, '--property=LoadState', '--value') != 'loaded':
            raise ValueError(f'Сервис {name} не найден.')
        directory = Path('/etc/systemd/system') / (name + '.d')
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / 'miniapp.conf'
        content = (ROOT / 'deploy' / 'miniapp-systemd.conf').read_text()
    else:
        # Do not accidentally start another bot.py alongside an unmanaged process.
        running = subprocess.run(['pgrep', '-f', r'(^|/)bot\.py(\s|$)'], capture_output=True)
        if running.returncode == 0:
            raise ValueError('Найден запущенный bot.py. Укажите его существующий systemd-сервис через --service.')
        if running.returncode != 1:
            raise ValueError('Не удалось проверить запущенные процессы бота.')
        if run('systemctl', 'show', name, '--property=LoadState', '--value') != 'not-found':
            raise ValueError(f'Имя {name} уже занято другим сервисом.')
        python = args.python or next((p for p in (ROOT / '.venv/bin/python', ROOT / 'venv/bin/python') if p.is_file()), Path(sys.executable))
        if not python.is_file():
            raise ValueError('Python не найден. Укажите --python /path/to/venv/bin/python')
        check = subprocess.run([str(python), '-c', 'import aiogram, aiomysql, aiohttp, telethon, dotenv'], capture_output=True)
        if check.returncode:
            raise ValueError('В выбранном Python нет зависимостей. Установите requirements.txt или укажите --python.')
        destination = Path('/etc/systemd/system') / name
        username = pwd.getpwuid(ROOT.stat().st_uid).pw_name
        content = render_unit(ROOT, python, username)
    if destination.exists() and destination.read_text() != content:
        raise ValueError(f'{destination} уже содержит другие настройки; файл оставлен без изменений.')
    destination.write_text(content)
    destination.chmod(0o644)
    run('systemctl', 'daemon-reload')
    run('systemctl', 'enable', name)
    run('systemctl', 'restart', name)
    print(f'Сервис: {name}\nКонфигурация: {destination}\nПроверка: systemctl is-active {name}')
    print('Проверка Mini App: curl --fail http://127.0.0.1:8080/api/health')
    print('Для публичного HTTPS установите Caddy и используйте deploy/Caddyfile.vps.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        # Do not print command stdout/stderr: they may contain runtime credentials.
        print(str(exc) if isinstance(exc, ValueError) else 'Не удалось настроить сервис. Проверьте systemd на сервере.', file=sys.stderr)
        sys.exit(1)
