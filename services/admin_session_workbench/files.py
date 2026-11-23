import json
import os
import sqlite3
import stat
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote


def ingest(path, dest, limit):
    path, dest = Path(path), Path(dest)
    dest.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.stat().st_size > limit:
        raise ValueError('Превышен размер загрузки')
    if path.suffix.lower() == '.session':
        import shutil
        shutil.copyfile(path, dest / 'account.session')
    elif path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 100 or sum(x.file_size for x in entries) > limit:
                raise ValueError('Слишком большой архив')
            seen = set()
            for entry in entries:
                name = PurePosixPath(entry.filename)
                if ('\\' in entry.filename or name.is_absolute() or '..' in name.parts
                    or ':' in entry.filename or stat.S_ISLNK(entry.external_attr >> 16)):
                    raise ValueError('Небезопасный путь ZIP')
                if entry.is_dir():
                    continue
                if len(name.parts) != 1 or name.suffix.lower() not in {'.session', '.json'} or name.name in seen:
                    raise ValueError('Нужны уникальные пары .session + .json в корне ZIP')
                seen.add(name.name)
                with archive.open(entry) as src, open(dest / name.name, 'wb') as out:
                    remaining = limit
                    while chunk := src.read(min(65536, remaining + 1)):
                        remaining -= len(chunk)
                        if remaining < 0:
                            raise ValueError('Превышен размер распаковки')
                        out.write(chunk)
    else:
        raise ValueError('Разрешены .session и .zip')
    sessions = list(dest.glob('*.session'))
    if not sessions:
        raise ValueError('Сессии не найдены')
    results = []
    for session in sessions:
        # Read-only validation: never let Telethon create an empty replacement database.
        with sqlite3.connect(f'file:{quote(str(session))}?mode=ro', uri=True) as db:
            row = db.execute('SELECT dc_id,server_address,port,auth_key FROM sessions').fetchone()
            if not row or not isinstance(row[3], bytes) or len(row[3]) != 256:
                raise ValueError('Неверный формат Telethon session')
        config_path = session.with_suffix('.json')
        config = json.loads(config_path.read_text()) if config_path.exists() else {}
        if path.suffix.lower() == '.zip' and not config_path.exists():
            raise ValueError('Нет парного JSON')
        if not isinstance(config, dict):
            raise ValueError('JSON должен быть объектом')
        os.chmod(session, 0o600)
        if config_path.exists():
            os.chmod(config_path, 0o600)
        for source_name, target_name in {'device':'device_model', 'sdk':'system_version', '2fa':'password'}.items():
            if target_name not in config and source_name in config:
                config[target_name] = config[source_name]
        accepted = {'device_model', 'system_version', 'app_version', 'lang_code', 'system_lang_code',
                    'proxy', 'password', 'twoFA', 'two_fa'}
        results.append((session, {key: value for key, value in config.items() if key in accepted}))
    return results


def persist_zip(root, ident, session, config):
    root = Path(root)
    root.mkdir(exist_ok=True, parents=True)
    target = root / f'{ident}.zip'
    temp = target.with_suffix('.tmp')
    # Never export password or proxy credentials implicitly.
    safe = {k: v for k, v in config.items() if k in {'device_model', 'system_version', 'app_version', 'lang_code', 'system_lang_code'}}
    try:
        with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.write(session, 'account.session')
            archive.writestr('account.json', json.dumps(safe, ensure_ascii=False))
        with open(temp, 'rb') as file:
            os.fsync(file.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, target)
        descriptor = os.open(root, os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return str(target)
    finally:
        temp.unlink(missing_ok=True)
