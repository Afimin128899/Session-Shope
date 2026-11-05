"""Persist sanitized provider incidents for the independent VPS monitor."""
from database.db import _get_pool


async def payment_health(provider, ok):
    if provider not in {'crypto','xrocket','lave','platega'}: return
    key='payments:'+provider
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            if ok:
                await cur.execute('UPDATE operational_incidents SET active=0,failures=0,last_seen=UTC_TIMESTAMP() WHERE incident_key=%s',(key,))
            else:
                await cur.execute('''INSERT INTO operational_incidents(incident_key,active,first_seen,last_seen)
                    VALUES(%s,1,UTC_TIMESTAMP(),UTC_TIMESTAMP()) ON DUPLICATE KEY UPDATE
                    first_seen=IF(active=0,UTC_TIMESTAMP(),first_seen),failures=IF(active=0,1,failures+1),
                    active=1,last_seen=UTC_TIMESTAMP()''',(key,))
