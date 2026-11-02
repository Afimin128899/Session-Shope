"""Validate the SQLite session endpoint before allowing any network connection."""
import ipaddress
import sqlite3
from contextlib import closing
from pathlib import Path

NETWORKS=tuple(ipaddress.ip_network(value) for value in (
    '149.154.160.0/20','91.108.4.0/22','91.108.8.0/22','91.108.12.0/22',
    '91.108.16.0/22','91.108.20.0/22','91.108.56.0/22',
    '2001:b28:f23d::/48','2001:b28:f23f::/48','2001:b28:f23c::/48','2001:67c:4e8::/48'))


def validate_session_file(path):
    path=Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size>8*1024*1024:
        raise ValueError('Файл сессии недоступен или превышает допустимый размер.')
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro&immutable=1',uri=True)) as connection:
            connection.execute('PRAGMA trusted_schema=OFF')
            connection.execute('PRAGMA query_only=ON')
            if connection.execute("SELECT type FROM sqlite_master WHERE name='sessions'").fetchone()!=('table',):
                raise ValueError('Файл не содержит таблицу сессии Telethon.')
            rows=connection.execute('SELECT dc_id,server_address,port,auth_key FROM sessions LIMIT 2').fetchall()
        if len(rows)!=1: raise ValueError('Файл должен содержать одну авторизованную сессию.')
        dc,address,port,key=rows[0]
        try: ip=ipaddress.ip_address(address)
        except ValueError: raise ValueError('Недопустимый адрес дата-центра.') from None
        if type(dc)is not int or type(port)is not int or dc not in range(1,6) or port not in {443,80,5222} or not any(ip in network for network in NETWORKS) or not isinstance(key,bytes) or len(key)!=256:
            raise ValueError('Недопустимый адрес дата-центра или ключ сессии.')
    except (sqlite3.Error,TypeError):
        raise ValueError('Не удалось прочитать безопасную сессию Telethon.') from None
