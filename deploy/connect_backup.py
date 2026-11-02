#!/usr/bin/env python3
"""Connect a selected offsite repository only after a successful test backup."""
import argparse
import fcntl
from getpass import getpass
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlsplit
from dotenv import dotenv_values
from deploy.backup_db import config, initialize, backup, verify, restic


def value(text):
    if not text or any(c in text for c in '\r\n\x00'):
        raise ValueError('Пустое значение или недопустимые управляющие символы.')
    return text


def serialize(values):
    # dotenv and systemd both accept double quoted escaped values. dotenv
    # interpolation must be disabled when loading credentials.
    return ''.join(key + '="' + value(str(item)).replace('\\','\\\\').replace('"','\\"') + '"\n' for key,item in values.items())


def repository(text, kind):
    text=value(text)
    if kind=='s3':
        if not text.startswith('s3:https://'):
            raise ValueError('Нужен адрес s3:https://host/bucket/path с проверяемым HTTPS.')
        url=urlsplit(text[3:])
        if not url.hostname or url.username or url.password or not url.path.strip('/') or url.query or url.fragment:
            raise ValueError('Некорректный адрес S3.')
    elif not re.fullmatch(r'sftp:[A-Za-z0-9_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*:/[A-Za-z0-9_./-]+',text):
        raise ValueError('Нужен адрес sftp:user@host:/absolute/path (без пароля в адресе).')
    return text


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--type',choices=['s3','sftp'],required=True)
    args=parser.parse_args()
    if os.geteuid()!=0:
        raise ValueError('Запускайте через sudo на VPS.')
    path=Path('/etc/session-shope/backup.env')
    current=dict(dotenv_values(path,interpolate=False))
    if not current.get('RESTIC_PASSWORD_FILE'):
        raise ValueError('Сначала настройте локальные копии через deploy.setup_backups.')
    proposed={key:current[key] for key in ('RESTIC_PASSWORD_FILE','BACKUP_DB_SOCKET') if current.get(key)}
    proposed['RESTIC_REPOSITORY']=repository(input('Адрес внешнего репозитория restic: ').strip(),args.type)
    if args.type=='s3':
        proposed['AWS_ACCESS_KEY_ID']=value(getpass('S3 Access Key ID (скрыто): '))
        proposed['AWS_SECRET_ACCESS_KEY']=value(getpass('S3 Secret Key (скрыто): '))
        region=input('Регион S3 (Enter — по умолчанию): ').strip()
        if region: proposed['AWS_DEFAULT_REGION']=value(region)
    else:
        print('Используется SSH-ключ root и проверенный known_hosts; отключения проверки ключа сервера нет.')
        proposed['RESTIC_SFTP_COMMAND']='ssh -oBatchMode=yes -oStrictHostKeyChecking=yes ' + proposed['RESTIC_REPOSITORY'][5:].split(':',1)[0] + ' -s sftp'
    # Scheduled backup and this switch cannot overlap. Never put credentials in argv.
    with open('/run/lock/session-shope-backup.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        clean=dict(os.environ)
        for key in list(clean):
            if key.startswith(('RESTIC_','AWS_','BACKUP_DB_')): clean.pop(key)
        environment=clean|proposed
        with patch_environment(environment):
            values,environment=config(args.project)
            initialize(environment)
            with tempfile.TemporaryDirectory(prefix='session-backup-connect-',dir='/run') as directory:
                backup(values,environment,directory)
                if values['DB_HOST'] in {'localhost','127.0.0.1','::1'}: verify(values,environment,directory)
                else: restic(environment,'check','--read-data')
        descriptor,temporary=tempfile.mkstemp(prefix='.backup-',dir=path.parent)
        try:
            with os.fdopen(descriptor,'w') as stream:
                stream.write(serialize(proposed));stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
    print('Внешняя копия проверена. Таймеры будут использовать новый репозиторий. Старые локальные снимки сохранены.')
    print('Сохраните ключ шифрования из RESTIC_PASSWORD_FILE отдельно от VPS: без него копию нельзя восстановить.')


class patch_environment:
    def __init__(self,environment): self.environment=environment
    def __enter__(self):
        self.previous=dict(os.environ);os.environ.clear();os.environ.update(self.environment)
    def __exit__(self,*exc): os.environ.clear();os.environ.update(self.previous)


if __name__=='__main__':
    try: main()
    except (ValueError,OSError):
        print('Подключение не завершено. Проверьте адрес, доступ, ключ и состояние базы. Конфигурация backup.env не переключена.',file=sys.stderr)
        sys.exit(1)
