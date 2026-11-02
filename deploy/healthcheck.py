#!/usr/bin/env python3
"""Independent systemd monitor: no log bodies, tokens or credentials in alerts."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import aiohttp
import aiomysql
from dotenv import dotenv_values


def unit(name):
    if not re.fullmatch(r'[A-Za-z0-9@_.:-]+\.service',name): raise ValueError('Некорректный сервис.')
    result=subprocess.run(['systemctl','show',name,'--property=LoadState,ActiveState,Result,ExecMainStatus,ExecMainExitTimestampMonotonic'],capture_output=True,text=True,timeout=10)
    if result.returncode: return {}
    return dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)


async def collect(project,service,session,settings):
    problems={}
    if unit(service).get('ActiveState')!='active': problems['bot']='Бот остановлен или завершился с ошибкой.'
    if unit('caddy.service').get('ActiveState')!='active': problems['https']='Caddy остановлен: HTTPS может быть недоступен.'
    try:
        async with session.get('http://127.0.0.1:8080/api/health',timeout=aiohttp.ClientTimeout(total=8)) as res:
            data=await res.json()
            if res.status!=200 or data.get('status')!='ok': raise ValueError
    except Exception: problems['miniapp']='Локальный Mini App не отвечает на проверку.'
    for name in ('session-shope-backup.service','session-shope-backup-check.service'):
        status=unit(name)
        if status.get('LoadState')!='loaded': problems[name]='Резервное копирование или проверка восстановления не настроены.'
        elif status.get('Result') not in (None,'success'): problems[name]='Задание резервного копирования или проверки восстановления завершилось с ошибкой.'
        elif name=='session-shope-backup.service' and status.get('ActiveState')!='activating':
            exited=int(status.get('ExecMainExitTimestampMonotonic') or 0)/1000000
            try:
                stamp=float(json.loads(Path('/var/lib/session-shope/backup-success.json').read_text())['completed_at'])
                stale=time.time()-stamp>30*3600
            except (OSError,ValueError,KeyError,TypeError):
                stale=not exited or time.monotonic()-exited>30*3600
            if stale: problems['backup-stale']='Нет подтверждённой успешной резервной копии за последние 30 часов. Проверьте backup-таймер.'
    if shutil.disk_usage(project).free < 1024**3: problems['disk']='На диске осталось меньше 1 ГБ.'
    connection=None
    try:
        connection=await aiomysql.connect(host=settings.get('DB_HOST','127.0.0.1'),port=int(settings.get('DB_PORT') or 3306),user=settings['DB_USER'],password=settings.get('DB_PASSWORD',''),db=settings['DB_NAME'],connect_timeout=5,autocommit=True)
        async with connection.cursor() as cur:
            await cur.execute('SELECT incident_key FROM operational_incidents WHERE active=1 AND failures>=3')
            for (key,) in await cur.fetchall():
                if key not in {'payments:crypto','payments:xrocket','payments:lave'}: continue
                problems[key]='Повторяются ошибки проверки оплат: '+key.split(':')[-1]+'. Проверьте ключ и доступность платёжного сервиса.'
    except Exception: problems['database']='Не удалось проверить базу магазина. Проверьте MariaDB и настройки подключения.'
    finally:
        if connection: connection.close()
    return problems


async def notify(session,token,admin,message):
    try:
        async with session.post('https://api.telegram.org/bot'+token+'/sendMessage',json={'chat_id':admin,'text':message},timeout=aiohttp.ClientTimeout(total=12)) as res:
            return res.status==200 and bool((await res.json()).get('ok'))
    except Exception: return False


async def deliver(session,settings,problems,state,now):
    admins={value.strip() for value in settings.get('ADMIN_IDS','').split(',') if value.strip().isdigit()}
    token=settings.get('BOT_TOKEN','')
    if not token or not admins: raise ValueError('Нет токена или ID администратора для мониторинга.')
    for admin in admins:
        previous=state.setdefault(admin,{})
        for key,text in problems.items():
            if key in previous and now-previous[key]<3600: continue
            if await notify(session,token,admin,'⚠️ Sband ACCS\n'+text+'\nПовторное напоминание — не чаще раза в час.'):
                previous[key]=now
        for key in list(previous):
            if key not in problems and await notify(session,token,admin,'✅ Sband ACCS: проблема устранена ('+key+').'):
                del previous[key]
    return state


async def main(args):
    if os.geteuid()!=0: raise ValueError('Монитор запускается root-сервисом systemd.')
    settings=dict(dotenv_values(args.project/'.env',interpolate=False))
    directory=Path('/var/lib/session-shope/monitor');directory.mkdir(parents=True,exist_ok=True);directory.chmod(0o700)
    path=directory/'state.json'
    try:
        state=json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(state,dict) or any(not isinstance(v,dict) or any(not isinstance(t,(int,float)) for t in v.values()) for v in state.values()): state={}
    except (ValueError,OSError): state={}
    async with aiohttp.ClientSession(trust_env=True) as session:
        problems=await collect(args.project,args.service,session,settings)
        state=await deliver(session,settings,problems,state,time.time())
    descriptor,temporary=tempfile.mkstemp(dir=directory,prefix='.state-')
    try:
        with os.fdopen(descriptor,'w') as stream: json.dump(state,stream)
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    print('Проверка завершена. Активных проблем:',len(problems))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--service',default='session-shope.service')
    try: asyncio.run(main(parser.parse_args()))
    except Exception: raise SystemExit('Мониторинг не выполнен: проверьте настройки и доступность служб. Секреты в журнал не выводятся.')
