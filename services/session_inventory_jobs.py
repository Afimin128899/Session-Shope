"""Administrator initiated inventory backups and re-authorization, delivered privately."""
import asyncio
import io
import json
import zipfile
from datetime import datetime, timezone
from aiogram.types import BufferedInputFile
from database import session_jobs
from database.admin_web import rows
from services.session_audit import session_file_bytes
from services.session_reauth import recreate


def archive_bytes(accounts, report):
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for account in accounts:
            metadata={key:account.get(key) for key in ('id','number','telegram_user_id','registration_date','password','is_premium','country','price','status')}
            metadata['phone']=metadata.pop('number')
            metadata['registration_date']=str(metadata['registration_date']) if metadata['registration_date'] else None
            metadata['registration_date_source']='store_metadata' if metadata['registration_date'] else 'unknown'
            metadata['string_session']=account['data']
            try:
                archive.writestr(f"account-{account['id']}.session",session_file_bytes(account['data']))
            except Exception:
                metadata['session_export_error']='sqlite_export_failed'
            archive.writestr(f"account-{account['id']}.json",json.dumps(metadata,ensure_ascii=False,default=str))
        archive.writestr('report.json',json.dumps(report,ensure_ascii=False,indent=2))
    return output.getvalue()


async def run(bot, admin, action):
    last=0;total=0
    snapshot=await rows("SELECT COALESCE(MAX(id),0) AS maximum FROM accounts WHERE status IN ('available','review')")
    maximum=snapshot[0]['maximum']
    stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    while last<maximum:
        batch=await rows("SELECT id FROM accounts WHERE status IN ('available','review') AND id>%s AND id<=%s ORDER BY id LIMIT 50",(last,maximum))
        if not batch: break
        report=[];accounts=[]
        for item in batch:
            last=item['id'];account=await session_jobs.claim(last)
            if not account:
                report.append({'id':last,'status':'skipped_busy'});continue
            try:
                if action=='reauthorize':
                    result=await recreate(account)
                    public={key:value for key,value in result.items() if key!='new_session'}
                    if result['status']=='ready':
                        if await session_jobs.save_new(admin,account,result):
                            account['data']=result['new_session'];account['telegram_user_id']=result['telegram_user_id'];public['status']='replaced'
                        else: public={'status':'failed','reason':'stock_changed'}
                    report.append({'id':last,**public})
                else:report.append({'id':last,'status':'exported'})
                accounts.append(account)
            finally:
                await session_jobs.release(account)
        await bot.send_document(admin,BufferedInputFile(await asyncio.to_thread(archive_bytes,accounts,report),filename=f'sessions-{action}-{stamp}-{last}.zip'),caption=f'Сессии и JSON: {len(accounts)}. Отчёт внутри. Данные до товара #{last}.')
        total+=len(accounts)
        if action=='reauthorize':
            await bot.send_message(admin,f'Обработано в партии: {len(accounts)}. Новая авторизация выполнена: {sum(r["status"]=="replaced" for r in report)}. Остальные результаты — в report.json.')
    await bot.send_message(admin,f'Готово. Отправлено аккаунтов: {total}. Занятые и проданные товары пропущены.')
