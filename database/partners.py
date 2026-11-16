"""Partner lifecycle and scoped wallets. Principal and promotional money never mix."""
import json
import re
import secrets
from decimal import Decimal
from database import db
from database.advertising import AccessDenied
from database.admin_tools import _transaction,_record
from database.admin_web import rows
from utils.partner_context import CURRENT,CONTENT,bot_id

LABELS={'btn_buy','btn_balance','btn_profile','btn_support','btn_purchases','btn_referral_system','btn_bonuses','btn_promo','btn_rules','btn_user_settings'}


async def init_schema(cur):
    for sql in [
    '''CREATE TABLE IF NOT EXISTS partner_bots (bot_id BIGINT PRIMARY KEY,owner_id BIGINT NOT NULL,username VARCHAR(32) NOT NULL,token_cipher VARBINARY(1024) NOT NULL,status VARCHAR(16) NOT NULL DEFAULT 'pending',content_json TEXT NOT NULL,offset_id BIGINT NOT NULL DEFAULT 0,lease_owner VARCHAR(36) DEFAULT NULL,lease_until DATETIME DEFAULT NULL,created_at DATETIME NOT NULL,approved_by BIGINT DEFAULT NULL,KEY partner_owner(owner_id)) ENGINE=InnoDB''',
    '''CREATE TABLE IF NOT EXISTS scoped_wallets (bot_id BIGINT NOT NULL,user_id BIGINT NOT NULL,cash DECIMAL(18,8) NOT NULL DEFAULT 0,bonus DECIMAL(18,8) NOT NULL DEFAULT 0,PRIMARY KEY(bot_id,user_id)) ENGINE=InnoDB''',
    '''CREATE TABLE IF NOT EXISTS order_wallet_funding (purchase_id BIGINT PRIMARY KEY,bot_id BIGINT NOT NULL,cash DECIMAL(18,8) NOT NULL,bonus DECIMAL(18,8) NOT NULL) ENGINE=InnoDB''',
    '''CREATE TABLE IF NOT EXISTS partner_settlements (bot_id BIGINT NOT NULL,user_id BIGINT NOT NULL,cash DECIMAL(18,8) NOT NULL,bonus_expired DECIMAL(18,8) NOT NULL,created_at DATETIME NOT NULL,PRIMARY KEY(bot_id,user_id)) ENGINE=InnoDB''',
    '''CREATE TABLE IF NOT EXISTS partner_transfers (token CHAR(32) PRIMARY KEY,user_id BIGINT NOT NULL,bot_id BIGINT NOT NULL,amount DECIMAL(18,8) NOT NULL,done TINYINT NOT NULL DEFAULT 0,expires_at DATETIME NOT NULL) ENGINE=InnoDB''',
    '''CREATE TABLE IF NOT EXISTS global_user_bans (user_id BIGINT NOT NULL,source_bot BIGINT NOT NULL,actor_id BIGINT NOT NULL,reason VARCHAR(300) NOT NULL,active TINYINT NOT NULL DEFAULT 1,created_at DATETIME NOT NULL,PRIMARY KEY(user_id,source_bot)) ENGINE=InnoDB''',
    '''CREATE TABLE IF NOT EXISTS main_bot_content (id INT PRIMARY KEY,content_json TEXT NOT NULL) ENGINE=InnoDB''']:
        await cur.execute(sql)
    await cur.execute('CREATE TABLE IF NOT EXISTS user_bot_routes (user_id BIGINT PRIMARY KEY,bot_id BIGINT NOT NULL) ENGINE=InnoDB')
    await cur.execute('CREATE TABLE IF NOT EXISTS bonus_reward_sources (event_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY) ENGINE=InnoDB')
    await cur.execute("INSERT IGNORE INTO main_bot_content VALUES(1,'{}')")


def owner(actor):
    from config import ADMIN_IDS
    if CURRENT.get() or actor not in ADMIN_IDS:raise AccessDenied('Доступ только владельцу основного бота.')


async def get(identity):
    found=await rows('SELECT * FROM partner_bots WHERE bot_id=%s',(identity,))
    return found[0] if found else None


def public(row):return {k:row[k] for k in ('bot_id','owner_id','username','status','created_at','approved_by')}


async def submit(user,identity,username,encrypted):
    if CURRENT.get():raise AccessDenied('Заявки подаются через основной бот.')
    if type(identity) is not int or identity<=0:raise ValueError('Некорректный ID бота.')
    async with _transaction() as cur:
        await cur.execute('INSERT INTO partner_bots(bot_id,owner_id,username,token_cipher,content_json,created_at) VALUES(%s,%s,%s,%s,%s,UTC_TIMESTAMP())',(identity,user,username,encrypted.decode('ascii'),'{}'))
        await _record(cur,user,'partner_request','partner',identity,{})


async def listing(actor):
    owner(actor)
    return [public(r) for r in await rows('SELECT * FROM partner_bots ORDER BY created_at DESC LIMIT 200')]


async def enable(actor,identity,enabled):
    owner(actor)
    async with _transaction() as cur:
        await cur.execute('SELECT status FROM partner_bots WHERE bot_id=%s FOR UPDATE',(identity,));r=await cur.fetchone()
        if not r or r['status']=='closed':raise ValueError('Бот не найден или окончательно закрыт.')
        await cur.execute('UPDATE partner_bots SET status=%s,approved_by=%s WHERE bot_id=%s',('enabled' if enabled else 'paused',actor,identity))
        await _record(cur,actor,'partner_enable' if enabled else 'partner_pause','partner',identity,{})


async def active(cur,identity=None):
    identity=bot_id() if identity is None else identity
    if not identity:return
    await cur.execute('SELECT status FROM partner_bots WHERE bot_id=%s LOCK IN SHARE MODE',(identity,));r=await cur.fetchone()
    if not r or r['status']!='enabled':raise ValueError('Партнёрский бот сейчас отключён.')


async def balances(user,identity=None):
    identity=bot_id() if identity is None else identity
    result=await rows('SELECT cash,bonus FROM scoped_wallets WHERE bot_id=%s AND user_id=%s',(identity,user))
    return result[0] if result else {'cash':Decimal(0),'bonus':Decimal(0)}


async def bonus_credit(cur,user,amount,identity=None):
    identity=bot_id() if identity is None else identity
    await active(cur,identity)
    await cur.execute('INSERT INTO scoped_wallets(bot_id,user_id,bonus) VALUES(%s,%s,%s) ON DUPLICATE KEY UPDATE bonus=bonus+VALUES(bonus)',(identity,user,amount))


async def lock_funds(cur,user,main_cash):
    identity=bot_id()
    if Decimal(str(main_cash))<0:raise ValueError('На основном балансе задолженность. Обратитесь в поддержку.')
    if identity:
        await cur.execute('SELECT bonus FROM scoped_wallets WHERE bot_id=0 AND user_id=%s FOR UPDATE',(user,));main=await cur.fetchone()
        if Decimal(str(main_cash))+min(Decimal(str(main['bonus'])) if main else Decimal(0),Decimal(0))<0:raise ValueError('На основном балансе задолженность. Обратитесь в поддержку.')
    await cur.execute('INSERT IGNORE INTO scoped_wallets(bot_id,user_id) VALUES(%s,%s)',(identity,user))
    await cur.execute('SELECT cash,bonus FROM scoped_wallets WHERE bot_id=%s AND user_id=%s FOR UPDATE',(identity,user));r=await cur.fetchone()
    return {'cash':Decimal(str(r['cash'])) if identity else Decimal(str(main_cash)),'bonus':Decimal(str(r['bonus'])),'bot_id':identity}


async def debit(cur,user,amount,funds):
    amount=Decimal(str(amount));bonus=min(max(funds['bonus'],Decimal(0)),amount);cash=amount-bonus
    if amount<0 or funds['cash']+funds['bonus']<amount:raise ValueError('Недостаточно средств на выбранном балансе.')
    if funds['bot_id']:
        await cur.execute('UPDATE scoped_wallets SET cash=cash-%s,bonus=bonus-%s WHERE bot_id=%s AND user_id=%s',(cash,bonus,funds['bot_id'],user))
    else:
        await cur.execute('UPDATE users SET balance = balance - %s WHERE id = %s',(cash,user))
        if bonus:await cur.execute('UPDATE scoped_wallets SET bonus=bonus-%s WHERE bot_id=0 AND user_id=%s',(bonus,user))
    return cash,bonus


async def record_funding(cur,purchase,cash,bonus,identity=None):
    await cur.execute('INSERT INTO order_wallet_funding VALUES(%s,%s,%s,%s)',(purchase,bot_id() if identity is None else identity,cash,bonus))


async def credit_refund(cur,user,funding):
    identity=funding['bot_id']
    if identity:
        await cur.execute('SELECT status FROM partner_bots WHERE bot_id=%s LOCK IN SHARE MODE',(identity,));r=await cur.fetchone()
        if r and r['status']=='closed':identity=0
    if not identity:
        await cur.execute('UPDATE users SET balance=balance+%s WHERE id=%s',(funding['cash'],user))
        await bonus_credit(cur,user,funding['bonus'],0)
    else:
        # Refunds stay available even while the bot is paused.
        await cur.execute('INSERT INTO scoped_wallets(bot_id,user_id,cash,bonus) VALUES(%s,%s,%s,%s) ON DUPLICATE KEY UPDATE cash=cash+VALUES(cash),bonus=bonus+VALUES(bonus)',(identity,user,funding['cash'],funding['bonus']))


async def quote_transfer(user,identity,value):
    if CURRENT.get():raise AccessDenied('Переводы подтверждаются в основном боте.')
    if type(identity) is not int or identity<=0:raise ValueError('Некорректный ID бота.')
    from utils.commerce_policy import money
    value=money(value);token=secrets.token_hex(16)
    async with _transaction() as cur:
        await active(cur,identity)
        await cur.execute('INSERT INTO partner_transfers(token,user_id,bot_id,amount,expires_at) VALUES(%s,%s,%s,%s,DATE_ADD(UTC_TIMESTAMP(),INTERVAL 15 MINUTE))',(token,user,identity,value))
    return token,value


async def transfer(user,token):
    if CURRENT.get():raise AccessDenied('Переводы подтверждаются в основном боте.')
    async with _transaction() as cur:
        await cur.execute('SELECT * FROM partner_transfers WHERE token=%s AND user_id=%s',(token,user));q=await cur.fetchone()
        if not q:raise ValueError('Подтверждение не найдено.')
        await active(cur,q['bot_id'])
        await cur.execute('SELECT balance FROM users WHERE id=%s FOR UPDATE',(user,));u=await cur.fetchone()
        await cur.execute('SELECT *,expires_at>UTC_TIMESTAMP() AS valid FROM partner_transfers WHERE token=%s FOR UPDATE',(token,));q=await cur.fetchone()
        if q['done']:return str(q['amount'])
        await cur.execute('SELECT bonus FROM scoped_wallets WHERE bot_id=0 AND user_id=%s FOR UPDATE',(user,));main=await cur.fetchone()
        debt=min(Decimal(str(main['bonus'])) if main else Decimal(0),Decimal(0))
        if not q['valid'] or not u or Decimal(str(u['balance']))+debt<q['amount']:raise ValueError('Недостаточно внесённых средств или подтверждение истекло. Бонусы переводить нельзя.')
        await cur.execute('UPDATE users SET balance=balance-%s WHERE id=%s',(q['amount'],user))
        await cur.execute('INSERT INTO scoped_wallets(bot_id,user_id,cash) VALUES(%s,%s,%s) ON DUPLICATE KEY UPDATE cash=cash+VALUES(cash)',(q['bot_id'],user,q['amount']))
        await cur.execute('UPDATE partner_transfers SET done=1 WHERE token=%s',(token,))
        await _record(cur,user,'partner_fund','partner',q['bot_id'],{'amount':str(q['amount'])})
        return str(q['amount'])


async def close(actor,identity):
    owner(actor)
    async with _transaction() as cur:
        await cur.execute('SELECT status FROM partner_bots WHERE bot_id=%s FOR UPDATE',(identity,));p=await cur.fetchone()
        if not p:raise ValueError('Бот не найден.')
        if p['status']=='closed':return
        await cur.execute('SELECT u.id FROM users u JOIN scoped_wallets w ON w.user_id=u.id WHERE w.bot_id=%s ORDER BY u.id FOR UPDATE',(identity,));await cur.fetchall()
        await cur.execute('SELECT * FROM scoped_wallets WHERE bot_id=%s ORDER BY user_id FOR UPDATE',(identity,));wallets=await cur.fetchall()
        for w in wallets:
            await cur.execute('INSERT INTO partner_settlements VALUES(%s,%s,%s,%s,UTC_TIMESTAMP())',(identity,w['user_id'],w['cash'],w['bonus']))
            await cur.execute('UPDATE users SET balance=balance+%s WHERE id=%s',(w['cash'],w['user_id']))
        await cur.execute('UPDATE scoped_wallets SET cash=0,bonus=0 WHERE bot_id=%s',(identity,))
        await cur.execute("UPDATE partner_bots SET status='closed' WHERE bot_id=%s",(identity,))
        await _record(cur,actor,'partner_close','partner',identity,{'wallets':len(wallets)})


async def content(identity):
    r=await get(identity) if identity else (await rows('SELECT content_json FROM main_bot_content WHERE id=1'))[0]
    return json.loads(r['content_json']) if r else {}


async def set_content(actor,identity,key,value):
    if CURRENT.get() and identity!=bot_id():raise AccessDenied('Можно менять только свой бот.')
    p=await get(identity) if identity else None
    if identity:
        if not p or actor!=p['owner_id']:
            owner(actor)
    else:owner(actor)
    if key not in LABELS|{'welcome','photo'} or not isinstance(value,str):raise ValueError('Поле недоступно.')
    limit=900 if key=='welcome' else 250 if key=='photo' else 50
    if len(value)>limit or (key=='photo' and value and (not value.startswith(f'partner-assets/{identity}/') or not re.fullmatch(r'partner-assets/[0-9]+/[0-9a-f]{32}\.(jpg|png)',value))):raise ValueError('Некорректное значение.')
    async with _transaction() as cur:
        if identity:await cur.execute('SELECT content_json FROM partner_bots WHERE bot_id=%s FOR UPDATE',(identity,))
        else:await cur.execute('SELECT content_json FROM main_bot_content WHERE id=1 FOR UPDATE')
        values=json.loads((await cur.fetchone())['content_json']);values[key]=value
        if identity:await cur.execute('UPDATE partner_bots SET content_json=%s WHERE bot_id=%s',(json.dumps(values,ensure_ascii=False),identity))
        else:await cur.execute('UPDATE main_bot_content SET content_json=%s WHERE id=1',(json.dumps(values,ensure_ascii=False),))
        await _record(cur,actor,'bot_content','partner',identity,{'key':key})


async def ban(actor,identity,user,reason,enabled=True):
    if CURRENT.get() and identity!=bot_id():raise AccessDenied('Доступ только к своему боту.')
    from config import ADMIN_IDS
    if type(user) is not int or not 0<user<=4503599627370495 or user in ADMIN_IDS or not isinstance(reason,str) or not 1<=len(reason)<=300 or type(enabled) is not bool:raise ValueError('Укажите корректный ID и причину; владельца блокировать нельзя.')
    if identity:
        p=await get(identity)
        if not p or actor!=p['owner_id'] or p['status']!='enabled':raise AccessDenied('Доступ запрещён.')
    else:owner(actor)
    async with _transaction() as cur:
        if not enabled and not identity:
            await cur.execute('UPDATE global_user_bans SET active=0 WHERE user_id=%s',(user,))
        else:
            await cur.execute('INSERT INTO global_user_bans VALUES(%s,%s,%s,%s,%s,UTC_TIMESTAMP()) ON DUPLICATE KEY UPDATE active=VALUES(active),reason=VALUES(reason),actor_id=VALUES(actor_id)',(user,identity,actor,reason,int(enabled)))
        await _record(cur,actor,'global_ban' if enabled else 'global_unban','user',user,{'source_bot':identity})


async def banned(user):
    from config import ADMIN_IDS
    return user not in ADMIN_IDS and bool(await rows('SELECT user_id FROM global_user_bans WHERE user_id=%s AND active=1 LIMIT 1',(user,)))


def order_clause(alias='p'):
    identity=bot_id()
    return f' AND EXISTS(SELECT 1 FROM order_wallet_funding wf WHERE wf.purchase_id={alias}.id AND wf.bot_id={identity})' if identity else ''


async def wallet_history(user,page=0):
    """Only events with an authoritative wallet origin are projected here."""
    result=await rows("""SELECT * FROM (
        SELECT CONCAT('purchase:',p.id) event_key,'purchase' kind,CAST(p.id AS CHAR) reference,
        p.paid_amount amount,'RUB' currency,STR_TO_DATE(p.date,'%%Y-%%m-%%d %%H:%%i:%%s') occurred_at
        FROM purchases p JOIN order_wallet_funding f ON f.purchase_id=p.id WHERE p.user_id=%s AND f.bot_id=%s
        UNION ALL SELECT CONCAT('refund:',r.purchase_id),'refund',CAST(r.purchase_id AS CHAR),r.amount,r.currency,r.created_at
        FROM order_refunds r JOIN order_wallet_funding f ON f.purchase_id=r.purchase_id WHERE r.user_id=%s AND f.bot_id=%s
        UNION ALL SELECT CONCAT('transfer:',token),'payment','Перевод из основного бота',amount,'RUB',DATE_SUB(expires_at,INTERVAL 15 MINUTE)
        FROM partner_transfers WHERE user_id=%s AND bot_id=%s AND done=1
        ) e ORDER BY occurred_at DESC,event_key DESC LIMIT 21 OFFSET %s""",(user,bot_id(),user,bot_id(),user,bot_id(),max(0,min(page,1000))*20))
    from database.activity import LABELS
    for row in result[:20]:
        row['label']=LABELS[row['kind']]
        row['occurred_at']=row['occurred_at'].isoformat() if row['occurred_at'] else None
    return {'items':result[:20],'has_more':len(result)>20,'note':'Операции выбранного магазина. Бонусы показаны отдельно в текущем балансе; внешние платежи находятся в основном боте.'}
