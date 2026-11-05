#!/usr/bin/env python3
"""Encrypted streaming DB backups. No plaintext dumps or credentials in argv."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time

from dotenv import dotenv_values

TAG = 'session-shope'
CORE_TABLES = ('users', 'accounts', 'purchases', 'settings', 'order_refunds', 'admin_audit_log', 'support_tickets', 'support_messages', 'account_reservations', 'shopping_cart', 'account_favorites', 'payment_invoices', 'daily_report_deliveries', 'purchase_reviews', 'operational_incidents', 'customer_events', 'replacement_orders', 'refund_approvals', 'stock_alerts', 'import_batches', 'import_items', 'inventory_identities', 'star_payments', 'reward_claims', 'referral_rewards', 'referral_daily_totals', 'referral_blocks')


def client_options(values):
    def quote(value):
        value = str(value)
        if any(c in value for c in '\r\n\x00'):
            raise ValueError('В настройках базы недопустимые управляющие символы.')
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
    port = int(values.get('DB_PORT') or 3306)
    if not 0 < port < 65536:
        raise ValueError('Некорректный порт базы.')
    lines = ['[client]', 'user=' + quote(values['DB_USER']), 'password=' + quote(values['DB_PASSWORD']),
             'default-character-set=utf8mb4']
    if values.get('DB_SOCKET'):
        if values['DB_HOST'] not in {'localhost', '127.0.0.1', '::1'}:
            raise ValueError('Unix socket нельзя использовать для удалённой базы.')
        lines += ['protocol=socket', 'socket=' + quote(values['DB_SOCKET'])]
    else:
        lines += ['host=' + quote(values['DB_HOST']), 'port=' + str(port)]
        if values['DB_HOST'] not in {'localhost', '127.0.0.1', '::1'}:
            lines += ['ssl=1', 'ssl-verify-server-cert=1',
                      'ssl-ca=' + quote(values.get('DB_SSL_CA') or '/etc/ssl/certs/ca-certificates.crt')]
    return '\n'.join(lines + [''])


def config(project):
    values = dict(dotenv_values(Path(project) / '.env'))
    values.update({k: v for k, v in os.environ.items() if k.startswith('DB_')})
    if os.environ.get('BACKUP_DB_SOCKET'):
        values['DB_SOCKET'] = os.environ['BACKUP_DB_SOCKET']
    if os.environ.get('BACKUP_DB_SSL_CA'):
        values['DB_SSL_CA'] = os.environ['BACKUP_DB_SSL_CA']
    if any(not values.get(name) for name in ('DB_HOST', 'DB_USER', 'DB_NAME')) or values.get('DB_PASSWORD') is None:
        raise ValueError('Для backup нужны DB_HOST, DB_USER, DB_PASSWORD и DB_NAME в .env или окружении сервиса.')
    if not re.fullmatch(r'[A-Za-z0-9_]{1,64}', values['DB_NAME']):
        raise ValueError('Имя базы для backup должно содержать только буквы, цифры и подчёркивание.')
    environment = dict(os.environ)
    if not environment.get('RESTIC_REPOSITORY') or not environment.get('RESTIC_PASSWORD_FILE'):
        raise ValueError('Не настроены RESTIC_REPOSITORY и RESTIC_PASSWORD_FILE.')
    key = Path(environment['RESTIC_PASSWORD_FILE'])
    if not key.is_file() or key.stat().st_mode & 0o077:
        raise ValueError('Ключ restic должен существовать и иметь права 600.')
    environment.pop('RESTIC_PASSWORD', None)
    return values, environment


def restic_command(environment):
    command = ['restic']
    if environment.get('RESTIC_SFTP_COMMAND'):
        command += ['-o', 'sftp.command=' + environment['RESTIC_SFTP_COMMAND']]
    return command


def restic(environment, *args):
    result = subprocess.run([*restic_command(environment), *args], env=environment, capture_output=True, text=True)
    if result.returncode:
        raise ValueError('Операция restic не выполнена. Проверьте репозиторий, ключ и доступ к хранилищу.')
    return result.stdout


def initialize(environment):
    existing = subprocess.run([*restic_command(environment), 'cat', 'config'], env=environment, capture_output=True)
    if existing.returncode:
        # restic refuses to initialize over an existing repository, including one
        # opened with an incorrect key. Verification remains enabled.
        restic(environment, 'init', '--repository-version', '2')
    restic(environment, 'cat', 'config')


def latest(environment):
    snapshots = json.loads(restic(environment, 'snapshots', '--tag', TAG, '--latest', '1', '--json'))
    if not snapshots:
        raise ValueError('Нет резервных копий Session Shope.')
    snapshot = max(snapshots, key=lambda item: item['time'])['id']
    if not re.fullmatch(r'[0-9a-f]{64}', snapshot):
        raise ValueError('Некорректный идентификатор снимка.')
    return snapshot


def private_file(path, text):
    with open(path, 'x') as stream:
        os.chmod(path, 0o600)
        stream.write(text)


def backup(values, environment, directory):
    options = Path(directory) / 'client.cnf'
    private_file(options, client_options(values))
    with tempfile.TemporaryFile() as dump_errors:
        dump = subprocess.Popen([
            'mariadb-dump', f'--defaults-extra-file={options}', '--single-transaction', '--quick',
            '--skip-lock-tables', '--no-tablespaces', '--hex-blob', values['DB_NAME'],
        ], stdout=subprocess.PIPE, stderr=dump_errors)
        try:
            saved = subprocess.run([*restic_command(environment), 'backup', '--stdin', '--stdin-filename', 'database.sql',
                                    '--tag', TAG, '--json'], env=environment, stdin=dump.stdout,
                                   capture_output=True, text=True)
        finally:
            dump.stdout.close()
            dump_status = dump.wait()
        summaries = []
        for line in saved.stdout.splitlines():
            try:
                item = json.loads(line)
                if item.get('message_type') == 'summary':
                    summaries.append(item)
            except (ValueError, AttributeError):
                continue
        snapshot = summaries[-1].get('snapshot_id', '') if summaries else ''
        if dump_status or saved.returncode:
            # A failed SQL producer can leave a partial stdin snapshot. Remove only
            # the snapshot created by this invocation, never another backup.
            if re.fullmatch(r'[0-9a-f]{8,64}', snapshot):
                restic(environment, 'forget', snapshot)
            raise ValueError(f'Backup не завершён: SQL exit={dump_status}, restic exit={saved.returncode}. Проверьте чтение базы и доступ к репозиторию.')
        # Some restic versions omit snapshot_id when the content is unchanged.
        snapshot = snapshot or latest(environment)
    restic(environment, 'check')
    restic(environment, 'forget', '--tag', TAG, '--keep-daily', '14', '--keep-weekly', '8', '--keep-monthly', '6', '--prune')
    print('Зашифрованная копия базы сохранена и проверена: ' + snapshot)


def root_sql(sql):
    result = subprocess.run(['mariadb', '--protocol=socket', '--batch', '--skip-column-names'],
                            input=sql, capture_output=True, text=True)
    if result.returncode:
        raise ValueError('Проверка восстановления требует локального root-доступа MariaDB через socket.')
    return result.stdout.strip()


def verify(values, environment, directory):
    restic(environment, 'check', '--read-data')
    if values['DB_HOST'] not in {'127.0.0.1', 'localhost', '::1'}:
        raise ValueError('Копия restic проверена. Для SQL-проверки нужна отдельная локальная тестовая MariaDB.')
    snapshot = latest(environment)
    suffix = secrets.token_hex(8)
    database, user = 'session_restore_check_' + suffix, 'sr_' + suffix
    password = secrets.token_hex(32)
    created = False
    try:
        root_sql(f'CREATE DATABASE `{database}` COLLATE utf8mb4_unicode_ci;')
        created = True
        root_sql(f"CREATE USER '{user}'@'127.0.0.1' IDENTIFIED BY '{password}';\n"
                 f"CREATE USER '{user}'@'localhost' IDENTIFIED BY '{password}';\n"
                 f"GRANT ALL PRIVILEGES ON `{database}`.* TO '{user}'@'127.0.0.1';\n"
                 f"GRANT ALL PRIVILEGES ON `{database}`.* TO '{user}'@'localhost';")
        options = Path(directory) / 'restore-client.cnf'
        private_file(options, client_options({'DB_HOST': '127.0.0.1', 'DB_PORT': '3306', 'DB_USER': user, 'DB_PASSWORD': password, 'DB_SOCKET': os.environ.get('BACKUP_DB_SOCKET', '/run/mysqld/mysqld.sock')}))
        with tempfile.TemporaryFile() as errors:
            source = subprocess.Popen([*restic_command(environment), 'dump', snapshot, 'database.sql'], env=environment,
                                      stdout=subprocess.PIPE, stderr=errors)
            try:
                restored = subprocess.run(['mariadb', f'--defaults-extra-file={options}', '--local-infile=0', database],
                                          stdin=source.stdout, stdout=subprocess.DEVNULL, stderr=errors)
            finally:
                source.stdout.close()
                status = source.wait()
            if status or restored.returncode:
                raise ValueError('SQL-копия не прошла восстановление в отдельную тестовую базу.')
        table_list = ','.join("'" + name + "'" for name in CORE_TABLES)
        count = root_sql(f"SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='{database}' AND TABLE_NAME IN ({table_list});")
        if count != str(len(CORE_TABLES)):
            raise ValueError('В восстановленной копии отсутствуют обязательные таблицы.')
        counts = root_sql('USE `' + database + '`;\n' + '\n'.join(f'SELECT COUNT(*) FROM `{table}`;' for table in CORE_TABLES)).splitlines()
        if len(counts) != len(CORE_TABLES) or not all(value.isdigit() for value in counts):
            raise ValueError('Не удалось проверить строки восстановленной копии.')
        print('Копия восстановлена и проверена в отдельной временной базе; рабочая база не изменялась.')
        return {'snapshot': snapshot, 'rows': dict(zip(CORE_TABLES, map(int, counts)))}
    finally:
        if created:
            root_sql(f'DROP DATABASE IF EXISTS `{database}`;\n'
                     f"DROP USER IF EXISTS '{user}'@'127.0.0.1';\n"
                     f"DROP USER IF EXISTS '{user}'@'localhost';")


def record_success(path=Path('/var/lib/session-shope/backup-success.json')):
    path.parent.mkdir(parents=True,exist_ok=True)
    descriptor,temporary=tempfile.mkstemp(prefix='.backup-success-',dir=path.parent)
    try:
        with os.fdopen(descriptor,'w') as stream:
            json.dump({'completed_at':time.time()},stream)
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'run', 'verify', 'check'])
    parser.add_argument('--project', type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError('Запускайте backup через systemd или sudo.')
    values, environment = config(args.project)
    with open('/run/lock/session-shope-backup.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with tempfile.TemporaryDirectory(prefix='session-shope-backup-', dir='/run') as directory:
            if args.action == 'init':
                initialize(environment)
            elif args.action == 'run':
                backup(values, environment, directory)
                record_success()
            elif args.action == 'verify':
                verify(values, environment, directory)
            else:
                restic(environment, 'check', '--read-data')
                print('Целостность зашифрованных данных проверена.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as exc:
        print(str(exc) if isinstance(exc, ValueError) else 'Ошибка backup: проверьте права и установку mariadb-client/restic.', file=sys.stderr)
        sys.exit(1)
