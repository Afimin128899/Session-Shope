"""Render bot UI with tgmacicons; preserve credentials, links and API payloads."""
from html import escape, unescape
from html.parser import HTMLParser
import re

from aiogram.client.default import Default
from aiogram.utils.text_decorations import html_decoration


def _base(char):
    value = ord(char)
    return (0x1F000 <= value <= 0x1FAFF or 0x2600 <= value <= 0x27BF
            or 0x2194 <= value <= 0x2199 or value in {0x21A9,0x21AA,0x231A,0x231B,0x24C2,0x25B6,0x25C0,0x2934,0x2935,0x2B50,0x2B55,0x3030,0x303D,0x3297,0x3299,0x203C,0x2049,0x2139}
            or 0x23E9 <= value <= 0x23F3 or 0x23F8 <= value <= 0x23FA
            or 0x25AA <= value <= 0x25AB or 0x25FB <= value <= 0x25FE
            or 0x2B05 <= value <= 0x2B07 or 0x2B1B <= value <= 0x2B1C)


def segments(text):
    """Yield plain text and complete emoji clusters without touching normal digits."""
    index = start = 0
    while index < len(text):
        char = text[index]
        keycap = re.match(r'[0-9#*]\ufe0f?\u20e3',text[index:]) if char in '0123456789#*' else None
        copyright_emoji = char in '©®™' and text[index+1:index+2]=='\ufe0f'
        if not (_base(char) or keycap or copyright_emoji):
            index += 1
            continue
        if start < index: yield False,text[start:index]
        end = index + (len(keycap[0]) if keycap else 1)
        if 0x1F1E6 <= ord(char) <= 0x1F1FF and end < len(text) and 0x1F1E6 <= ord(text[end]) <= 0x1F1FF:
            end += 1
        while end < len(text):
            value=ord(text[end])
            if text[end] in '\ufe0e\ufe0f' or 0x1F3FB <= value <= 0x1F3FF or 0xE0020 <= value <= 0xE007F:
                end += 1
            elif text[end]=='\u200d' and end+1 < len(text) and _base(text[end+1]):
                end += 2
            else:
                break
        yield True,text[index:end]
        index = start = end
    if start < len(text): yield False,text[start:]


def strip_emojis(text):
    return ''.join(value for emoji,value in segments(text) if not emoji).replace('\ufe0f','').replace('\u200d','')


def _plain_fallback(text):
    # Never turn an emoji-only failure or warning into a success notification.
    values={value.replace('\ufe0f','') for emoji,value in segments(text) if emoji}
    if values & {'❌','✖','⚠','❗','❕'}: return 'Внимание'
    if values & {'✅','✔'}: return 'Готово'
    if values & {'⏳','⌛','🕒','⏱'}: return 'Подождите'
    return 'Сообщение'


def identity(emoji):
    from utils.button_icons import PACK_EMOJIS, CANDIDATES, pack_icon_for, normalized
    key=normalized(emoji)
    if key in PACK_EMOJIS: return PACK_EMOJIS[key]
    for role,choices in CANDIDATES.items():
        if key in {normalized(choice) for choice in choices}:
            return pack_icon_for(role)
    return None


def legacy_identity(old_id, body=''):
    from utils.button_icons import PACK_EMOJIS, PACK_ICONS, FALLBACK, pack_icon_for
    if old_id in {*PACK_EMOJIS.values(),*PACK_ICONS.values()}: return old_id
    for emoji,value in segments(unescape(body)):
        if emoji and (found:=identity(value)): return found
    return next((pack_icon_for(role) for role,old in FALLBACK.items() if old==old_id and pack_icon_for(role)),None)


def _html_data(text):
    result=[]
    for emoji,value in segments(text):
        if not emoji:
            result.append(escape(value,quote=False))
        elif found:=identity(value):
            result.append(f'<tg-emoji emoji-id="{found}">{escape(value,quote=False)}</tg-emoji>')
    return ''.join(result)


class _Renderer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.output=[]
        self.protected=0
        self.custom=None

    def handle_starttag(self,tag,attrs):
        raw=self.get_starttag_text()
        if self.custom is not None:
            self.custom['body'].append(raw)
        elif tag=='tg-emoji' and not self.protected:
            self.custom={'id':dict(attrs).get('emoji-id'),'body':[]}
        else:
            if tag in {'code','pre'}: self.protected+=1
            self.output.append(raw)

    def handle_endtag(self,tag):
        if self.custom is not None:
            if tag!='tg-emoji':
                self.custom['body'].append(f'</{tag}>')
                return
            body=''.join(self.custom['body'])
            found=legacy_identity(self.custom['id'],body)
            if found:
                self.output.append(f'<tg-emoji emoji-id="{found}">{body}</tg-emoji>')
            else:
                self.output.append(_html_data(unescape(body)))
            self.custom=None
            return
        self.output.append(f'</{tag}>')
        if tag in {'code','pre'}: self.protected=max(0,self.protected-1)

    def handle_data(self,data):
        if self.custom is not None: self.custom['body'].append(data)
        else: self.output.append(data if self.protected else _html_data(data))

    def _entity(self,raw):
        if self.custom is not None: self.custom['body'].append(raw)
        elif self.protected: self.output.append(raw)
        else:
            decoded=unescape(raw)
            self.output.append(_html_data(decoded) if any(is_emoji for is_emoji,_ in segments(decoded)) else raw)

    def handle_entityref(self,name): self._entity('&'+name+';')
    def handle_charref(self,name): self._entity('&#'+name+';')


def render_html(text):
    parser=_Renderer();parser.feed(text);parser.close()
    if parser.custom is not None:
        # Incomplete custom markup must not swallow the remainder of a message.
        parser.output.append(_html_data(unescape(''.join(parser.custom['body']))))
    return ''.join(parser.output)


def html_icon(role):
    from utils.button_icons import CANDIDATES, pack_icon_for
    found=pack_icon_for(role)
    return f'<tg-emoji emoji-id="{found}">{CANDIDATES[role][0]}</tg-emoji>' if found else ''


def _content_updates(item,bot):
    updates={}
    mode=getattr(item,'parse_mode',None)
    if isinstance(mode,Default): mode=getattr(getattr(bot,'default',None),'parse_mode',None)
    for field,entity_field in [('text','entities'),('caption','caption_entities')]:
        original=getattr(item,field,None)
        if not isinstance(original,str) or 'parse_mode' not in type(item).model_fields:
            continue
        entities=getattr(item,entity_field,None)
        if entities:
            source=html_decoration.unparse(original,entities)
        elif mode in {'HTML','html'}:
            source=original
        elif mode in {'Markdown','MarkdownV2'}:
            # Existing bot messages use HTML. Keep any explicit Markdown syntax.
            chunks=re.split(r'(```[\s\S]*?```|`[^`]*`)',original)
            rendered=''.join(chunk if chunk.startswith('`') else strip_emojis(chunk) for chunk in chunks)
            if rendered!=original: updates[field]=rendered
            continue
        else:
            source=escape(original,quote=False)
        rendered=render_html(source)
        if field=='text' and rendered!=source and not unescape(re.sub(r'<[^>]*>','',rendered)).strip(): rendered=_plain_fallback(original)
        if rendered!=source:
            updates.update({field:rendered,'parse_mode':'HTML',entity_field:None})
    return updates


def format_method(method,bot):
    """Only UI fields change. Invoice payloads, amounts, files and copied data stay exact."""
    updates={}
    name=getattr(method,'__api_method__','')
    if name not in {'copyMessage','forwardMessage','copyMessages','forwardMessages'}:
        updates.update(_content_updates(method,bot))
        for field in ('text','title','description','error_message'):
            value=getattr(method,field,None)
            if not isinstance(value,str) or (field=='text' and 'parse_mode' in type(method).model_fields): continue
            clean=strip_emojis(value)
            if clean!=value:
                clean=clean.strip()
                updates[field]=clean or ('Оплата' if field in {'title','description'} else 'Не удалось выполнить действие.' if field=='error_message' else _plain_fallback(value))
        media=getattr(method,'media',None)
        if media is not None:
            values=media if isinstance(media,list) else [media]
            transformed=[];changed=False
            for value in values:
                if hasattr(type(value),'model_fields'):
                    fields=_content_updates(value,bot)
                    transformed.append(value.model_copy(update=fields) if fields else value)
                    changed|=bool(fields)
                else: transformed.append(value)
            if changed: updates['media']=transformed if isinstance(media,list) else transformed[0]
    return method.model_copy(update=updates) if updates else method
