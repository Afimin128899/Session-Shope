"""Read only explicit registration metadata; never infer it from session creation."""
import json
from datetime import date, datetime, timezone


def parse_metadata(content):
    if len(content)>65536:
        raise ValueError('JSON должен быть не больше 64 КБ.')
    try:
        value=json.loads(content.decode('utf-8-sig'))
    except (ValueError,UnicodeError):
        raise ValueError('Не удалось прочитать JSON.') from None
    if not isinstance(value,dict):
        raise ValueError('JSON должен содержать объект с данными аккаунта.')
    registered=value.get('registration_date',value.get('register_date'))
    result={key:value[key] for key in ('phone','user_id','telegram_user_id') if key in value}
    result['registration_date']=None
    if registered not in (None,''):
        try:
            if type(registered) in (int,float):
                registered=datetime.fromtimestamp(registered,timezone.utc).date()
            elif isinstance(registered,str):
                registered=date.fromisoformat(registered)
            else:
                raise ValueError
            if not date(2013,1,1)<=registered<=datetime.now(timezone.utc).date(): raise ValueError
        except (ValueError,OverflowError,OSError):
            raise ValueError('Дата регистрации в JSON должна быть YYYY-MM-DD или Unix timestamp, без будущих дат.') from None
        result['registration_date']=registered.isoformat()
    return result


def match_identity(metadata, phone, identity):
    digits=lambda x: ''.join(c for c in str(x) if c.isascii() and c.isdigit())
    if metadata.get('phone') is not None and digits(metadata['phone'])!=digits(phone):
        raise ValueError('Номер в JSON не совпадает с сессией.')
    for key in ('user_id','telegram_user_id'):
        if key in metadata and str(metadata[key])!=str(identity):
            raise ValueError('Telegram ID в JSON не совпадает с сессией.')
