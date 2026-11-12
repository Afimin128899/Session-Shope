"""Bounded ZIP inspection. Only private temporary .session files reach Telethon."""
import asyncio
import io
import os
import shutil
import time
import stat
import tempfile
import zipfile
from pathlib import Path,PurePosixPath
from database import imports
from database.admin_web import rows

MAX_UPLOAD=8*1024*1024
MAX_FILE=1024*1024
MAX_TOTAL=32*1024*1024
GATE=asyncio.Semaphore(2)


def inspect_archive(data):
    if not data or len(data)>MAX_UPLOAD: raise ValueError('Архив должен быть ZIP размером до 8 МБ.')
    try:
        archive=zipfile.ZipFile(io.BytesIO(data));entries=archive.infolist()
        if not entries or len(entries)>120: raise ValueError('В архиве допускается до 100 сессий и 20 служебных записей.')
        total=0;files=[];names=set()
        for entry in entries:
            name=entry.filename
            path=PurePosixPath(name)
            if name.startswith('/') or '\\' in name or ':' in name or '..' in path.parts or '\x00' in name or entry.flag_bits&1 or stat.S_ISLNK(entry.external_attr>>16): raise ValueError('Архив содержит недопустимые пути, ссылки или шифрование.')
            if entry.is_dir(): continue
            if name in names: raise ValueError('Повторяющиеся имена файлов в архиве.')
            names.add(name)
            if not name.lower().endswith('.session'): raise ValueError('ZIP должен содержать только файлы .session; уберите JSON, архивы и другие файлы.')
            if entry.file_size>MAX_FILE or entry.file_size<0 or entry.file_size>max(1,entry.compress_size)*100: raise ValueError('Слишком большой или чрезмерно сжатый файл.')
            total+=entry.file_size
            if total>MAX_TOTAL or len(files)>=100: raise ValueError('Допускается до 100 сессий, общий размер до 32 МБ.')
            content=archive.read(entry)
            if len(content)!=entry.file_size: raise ValueError('Размер файла не совпадает с описанием ZIP.')
            files.append((str(path)[:200],content))
        if not files: raise ValueError('В архиве нет .session файлов.')
        return files
    except (zipfile.BadZipFile,RuntimeError,NotImplementedError): raise ValueError('Не удалось прочитать ZIP.') from None


async def process(admin,batch,files,verifier=None):
    if verifier is None:
        from services.telethon_auth import import_session_file
        verifier=import_session_file
    seen=set()
    try:
        async with GATE:
            for label,content in files:
                draft=await imports.preview(admin,batch)
                if draft['status']!='checking': return
                if not content.startswith(b'SQLite format 3\x00'):
                    await imports.add_item(batch,label,'error',error='Файл не является SQLite .session.')
                    continue
                metadata={}
                with tempfile.TemporaryDirectory(prefix='sband-import-') as directory:
                    path=Path(directory)/'account.session';path.write_bytes(content);path.chmod(0o600)
                    try:
                        session,phone,error=await asyncio.wait_for(verifier(str(path),metadata=metadata),timeout=25)
                    except Exception:
                        session=phone=None;error='Проверка не завершилась.'
                if metadata.get('rejection') == 'frozen':
                    from services.account_health import FROZEN_MESSAGE
                    await imports.add_item(batch,label,'error',error=FROZEN_MESSAGE)
                    continue
                if not session or not phone or not metadata.get('telegram_user_id'):
                    await imports.add_item(batch,label,'error',error='Не удалось подтвердить сессию. Проверьте авторизацию и доступность Telegram.')
                    continue
                from utils.commerce_policy import require_phone
                try:
                    require_phone(phone)
                except ValueError as exc:
                    await imports.add_item(batch,label,'error',error=str(exc))
                    continue
                identity=metadata['telegram_user_id']
                existing=await rows("SELECT id FROM accounts WHERE telegram_user_id=%s OR REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(number,'+',''),' ',''),'-',''),'(',''),')','')=%s OR data=%s LIMIT 1",(identity,''.join(c for c in phone if c.isdigit()),session))
                if identity in seen or existing:
                    await imports.add_item(batch,label,'duplicate',error='Аккаунт повторяется в архиве или уже есть в магазине.',phone=phone,telegram_id=identity)
                else:
                    seen.add(identity)
                    await imports.add_item(batch,label,'ready',phone=phone,telegram_id=identity,premium=metadata.get('is_premium'),session=session)
            await imports.finish(batch)
    except asyncio.CancelledError:
        await imports.finish(batch,'failed');raise
    except Exception:
        await imports.finish(batch,'failed')
    finally:
        files.clear()


def cleanup_temporary_files():
    # Only our private generated directories, owned by this process user, after TTL.
    for path in Path(tempfile.gettempdir()).glob('sband-import-*'):
        try:
            info=path.lstat()
            if stat.S_ISDIR(info.st_mode) and info.st_uid==os.geteuid() and time.time()-info.st_mtime>3600:
                shutil.rmtree(path)
        except OSError:
            continue


async def housekeeping():
    while True:
        try:
            await asyncio.to_thread(cleanup_temporary_files)
            await imports.cleanup()
        except Exception: pass
        await asyncio.sleep(300)
