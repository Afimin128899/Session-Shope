"""Public, cacheable discovery documents for search and AI crawlers."""
import json
from pathlib import Path

from aiohttp import web


ROOT = Path(__file__).parent
BASE_URL = 'https://sbandsub.space'
PUBLIC_PATHS = {
    '/robots.txt', '/llms.txt', '/llms-full.txt', '/ai.txt',
    '/sitemap.xml', '/summary.json', '/feed.xml', '/index.md', '/about.md',
    '/.well-known/ai.txt', '/ai/summary.json', '/ai/faq.json',
    '/ai/service.json',
}


def _text(name, content_type='text/plain'):
    async def handler(_request):
        return web.Response(
            text=(ROOT / name).read_text(encoding='utf-8'),
            content_type=content_type,
            charset='utf-8',
        )
    return handler


def wants_markdown(request):
    """Offer a crawlable representation without changing normal browser HTML."""
    return 'text/markdown' in request.headers.get('Accept', '').lower()


def markdown_response(name):
    canonical = BASE_URL + ('/about' if name == 'about.md' else '/')
    return web.Response(
        text=(ROOT / name).read_text(encoding='utf-8'),
        content_type='text/markdown',
        charset='utf-8',
        headers={'Vary': 'Accept', 'Link': f'<{canonical}>; rel="canonical"'},
    )


def _markdown(name):
    async def handler(_request):
        return markdown_response(name)
    return handler


async def sitemap(_request):
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{BASE_URL}/</loc>
    <lastmod>2026-11-20</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>{BASE_URL}/about</loc>
    <lastmod>2026-11-20</lastmod>
    <changefreq>daily</changefreq>
    <priority>0.8</priority>
  </url>
</urlset>
'''
    return web.Response(text=xml, content_type='application/xml', charset='utf-8')


async def summary(_request):
    data = {
        'name': 'SBAND ACCS',
        'url': BASE_URL + '/',
        'language': 'ru',
        'description': (
            'Магазин Telegram-аккаунтов с каталогом по странам, '
            'ценой до оплаты и выдачей заказа в личном кабинете.'
        ),
        'offers': 'Telegram-аккаунты из текущего наличия',
        'authentication': ['Telegram', 'email one-time code'],
        'public_pages': [BASE_URL + '/', BASE_URL + '/about'],
        'documents': {
            'llms': BASE_URL + '/llms.txt',
            'llms_full': BASE_URL + '/llms-full.txt',
            'sitemap': BASE_URL + '/sitemap.xml',
            'feed': BASE_URL + '/feed.xml',
            'faq': BASE_URL + '/ai/faq.json',
        },
        'dateModified': '2026-11-20',
    }
    return web.Response(
        text=json.dumps(data, ensure_ascii=False, indent=2),
        content_type='application/json',
        charset='utf-8',
    )


async def faq(_request):
    data = {
        '@context': 'https://schema.org',
        '@type': 'FAQPage',
        'mainEntity': [
            {
                '@type': 'Question',
                'name': 'Что продаёт SBAND ACCS?',
                'acceptedAnswer': {
                    '@type': 'Answer',
                    'text': 'SBAND ACCS продаёт Telegram-аккаунты из текущего наличия, сгруппированные по странам и характеристикам.',
                },
            },
            {
                '@type': 'Question',
                'name': 'Когда покупатель видит окончательную цену?',
                'acceptedAnswer': {
                    '@type': 'Answer',
                    'text': 'Цена, характеристики и срок гарантии показываются до подтверждения покупки и повторно проверяются сервером при оплате.',
                },
            },
            {
                '@type': 'Question',
                'name': 'Где получить оплаченный заказ?',
                'acceptedAnswer': {
                    '@type': 'Answer',
                    'text': 'Данные оплаченного заказа сохраняются в личном кабинете покупателя в разделе «Мои покупки».',
                },
            },
        ],
        'dateModified': '2026-11-20',
    }
    return web.Response(
        text=json.dumps(data, ensure_ascii=False, indent=2),
        content_type='application/json',
        charset='utf-8',
    )


async def service(_request):
    data = {
        '@context': 'https://schema.org',
        '@type': 'Service',
        'name': 'Каталог SBAND ACCS',
        'provider': {
            '@type': 'Organization',
            'name': 'SBAND ACCS',
            'url': BASE_URL + '/',
        },
        'serviceType': 'Продажа Telegram-аккаунтов из текущего наличия',
        'areaServed': 'Онлайн',
        'url': BASE_URL + '/',
        'termsOfService': BASE_URL + '/about',
    }
    return web.Response(
        text=json.dumps(data, ensure_ascii=False, indent=2),
        content_type='application/json',
        charset='utf-8',
    )


async def feed(_request):
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>SBAND ACCS</title>
    <link>{BASE_URL}/</link>
    <description>Публичная информация магазина Telegram-аккаунтов SBAND ACCS.</description>
    <language>ru</language>
    <lastBuildDate>Fri, 20 Nov 2026 00:00:00 GMT</lastBuildDate>
    <item>
      <title>SBAND ACCS — каталог и порядок покупки</title>
      <link>{BASE_URL}/</link>
      <guid isPermaLink="true">{BASE_URL}/</guid>
      <pubDate>Fri, 20 Nov 2026 00:00:00 GMT</pubDate>
      <description>Как выбрать Telegram-аккаунт, проверить цену и получить заказ.</description>
    </item>
    <item>
      <title>Цены, документы и поддержка</title>
      <link>{BASE_URL}/about</link>
      <guid isPermaLink="true">{BASE_URL}/about</guid>
      <pubDate>Fri, 20 Nov 2026 00:00:00 GMT</pubDate>
      <description>Актуальное наличие, диапазоны цен, способы оплаты и документы.</description>
    </item>
  </channel>
</rss>
'''
    return web.Response(text=xml, content_type='application/rss+xml', charset='utf-8')


def register(app):
    app.add_routes([
        web.get('/robots.txt', _text('robots.txt')),
        web.get('/llms.txt', _text('llms.txt')),
        web.get('/llms-full.txt', _text('llms-full.txt')),
        web.get('/ai.txt', _text('ai.txt')),
        web.get('/.well-known/ai.txt', _text('ai.txt')),
        web.get('/sitemap.xml', sitemap),
        web.get('/summary.json', summary),
        web.get('/ai/summary.json', summary),
        web.get('/ai/faq.json', faq),
        web.get('/ai/service.json', service),
        web.get('/feed.xml', feed),
        web.get('/index.md', _markdown('homepage.md')),
        web.get('/about.md', _markdown('about.md')),
    ])
