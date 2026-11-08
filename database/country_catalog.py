"""Seed popular destinations without re-enabling or renaming existing categories."""
from utils.country_codes import COUNTRY_MAP
POPULAR = 'us ca gb de fr es it nl pl pt se no fi ch at tr kz uz kg ge am az in id my ph vn th bd pk br ar cl co mx pe au nz za eg ae sa il jp kr sg'.split()

async def seed(cur):
    await cur.execute("INSERT IGNORE INTO settings(`key`,`value`) VALUES('popular_countries_v1','1')")
    if cur.rowcount != 1:
        return
    names = {}
    for name, flag in COUNTRY_MAP.values():
        if len(flag) == 2:
            code = ''.join(chr(ord(c)-0x1F1E6+97) for c in flag)
            names.setdefault(code, (name, flag))
    names.update(ca=('Канада','🇨🇦'), kz=('Казахстан','🇰🇿'))
    for code in POPULAR:
        if code in names:
            name, flag = names[code]
            await cur.execute('INSERT IGNORE INTO categories(slug,name,emoji,is_active) VALUES(%s,%s,%s,1)', (code, name+' '+flag, flag))
