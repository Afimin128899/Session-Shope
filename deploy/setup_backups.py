#!/usr/bin/env python3
"""Install encrypted backup and restore-check timers for the current checkout."""
import argparse
import os
from pathlib import Path
import secrets
import subprocess
import sys

from dotenv import dotenv_values
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy.create_service import unit_quote


PREFIX = '# Managed by Session Shope backups\n'


def units(project, python, local=True):
    header = PREFIX + '# Project: ' + str(project) + '\n'
    command = f'{unit_quote(str(python))} {unit_quote(str(project / "deploy/backup_db.py"))}'
    result = {}
    for name, action in [('backup', 'run'), ('backup-check', 'verify' if local else 'check')]:
        result[f'session-shope-{name}.service'] = header + f'''[Unit]
Description=Session Shope encrypted database {name}
Wants=network-online.target
After=network-online.target mariadb.service

[Service]
Type=oneshot
User=root
EnvironmentFile=/etc/session-shope/backup.env
WorkingDirectory={str(project).replace('%', '%%')}
ExecStart={command} {action} --project {unit_quote(str(project))}
TimeoutStartSec=30min
UMask=0077
Nice=10
'''
    for name, calendar in [('backup', '*-*-* 04:00:00 Europe/Moscow'), ('backup-check', 'Sun *-*-* 05:00:00 Europe/Moscow')]:
        result[f'session-shope-{name}.timer'] = header + f'''[Unit]
Description=Session Shope scheduled {name}

[Timer]
OnCalendar={calendar}
Persistent=true
RandomizedDelaySec=10min
Unit=session-shope-{name}.service

[Install]
WantedBy=timers.target
'''
    return result


def save_unit(path, contents):
    if path.exists() and not path.read_text().startswith(contents.split('[Unit]', 1)[0]):
        raise ValueError(f'Существующий {path.name} относится к другой конфигурации, файл не изменён.')
    path.write_text(contents)
    path.chmod(0o644)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError('Нужен sudo для настройки таймеров backup.')
    project = args.project.resolve()
    settings = dict(dotenv_values(project / '.env'))
    local = settings.get('DB_HOST') in {'127.0.0.1', 'localhost', '::1'}
    config_dir = Path('/etc/session-shope')
    config_dir.mkdir(parents=True, exist_ok=True)
    config_dir.chmod(0o700)
    config_file = config_dir / 'backup.env'
    key = config_dir / 'backup-password'
    repository = Path('/var/backups/session-shope/restic')
    if not config_file.exists():
        if repository.exists() and any(repository.iterdir()):
            raise ValueError('Репозиторий backup уже существует, но конфигурация отсутствует. Восстановите прежний ключ и backup.env.')
        if not key.exists():
            with open(key, 'x') as stream:
                key.chmod(0o600)
                stream.write(secrets.token_urlsafe(48) + '\n')
        repository.mkdir(parents=True, exist_ok=True)
        repository.chmod(0o700)
        with open(config_file, 'x') as stream:
            config_file.chmod(0o600)
            stream.write(f'RESTIC_REPOSITORY={repository}\nRESTIC_PASSWORD_FILE={key}\n')
            if local and str(settings.get('DB_PORT') or '3306') == '3306' and Path('/run/mysqld/mysqld.sock').exists():
                stream.write('BACKUP_DB_SOCKET=/run/mysqld/mysqld.sock\n')
    config_file.chmod(0o600)
    variables = dict(dotenv_values(config_file))
    if any(value is None for value in variables.values()):
        raise ValueError('Некорректная настройка backup.env.')
    environment = dict(os.environ) | variables
    python = Path(sys.executable)
    # Initialize before enabling scheduled jobs. Existing repositories are verified.
    subprocess.run([str(python), '-m', 'deploy.backup_db', 'init', '--project', str(project)], cwd=project, env=environment, check=True)
    for name, contents in units(project, python, local).items():
        save_unit(Path('/etc/systemd/system') / name, contents)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', '--now', 'session-shope-backup.timer', 'session-shope-backup-check.timer'], check=True)
    subprocess.run(['systemctl', 'start', 'session-shope-backup.service'], check=True)
    subprocess.run(['systemctl', 'start', 'session-shope-backup-check.service'], check=True)
    print('Backup: ежедневно около 04:00 МСК. Проверка восстановления: по воскресеньям около 05:00 МСК.')
    print('Конфигурация: /etc/session-shope/backup.env. Ключ: /etc/session-shope/backup-password.')
    if environment.get('RESTIC_REPOSITORY', '').startswith('/'):
        print('Копии пока находятся на VPS. Для защиты от потери VPS подключите внешнее хранилище и сохраните ключ отдельно.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(str(exc) if isinstance(exc, ValueError) else 'Не удалось настроить backup. Проверьте journalctl -u session-shope-backup -u session-shope-backup-check.', file=sys.stderr)
        sys.exit(1)
