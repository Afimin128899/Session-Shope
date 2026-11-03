"""Replay this bot's Stars invoice history through the idempotent ledger.

Offset pagination has no snapshot cursor. Each batch re-reads the head, then
continues a durable, overlapping full sweep. A page checkpoint is saved only
after every applicable receipt on it has reached the ledger. Known receipts do
not stop a sweep, and complete sweeps always restart at zero.
"""
import asyncio
from dataclasses import dataclass
import logging
import re

from aiogram.exceptions import TelegramRetryAfter
from database import db

logger = logging.getLogger(__name__)
CURSOR_KEY = 'stars_reconcile_offset'
PAGE_SIZE = 100
PAGE_STEP = 80
MAX_PAGES = 5


@dataclass(frozen=True)
class Entry:
    direction: str
    user_id: int
    invoice_id: str | None
    stars: int
    charge_id: str


def _store():
    from database import stars
    return stars


def _entry(transaction, direction):
    source = getattr(transaction, 'source', None)
    receiver = getattr(transaction, 'receiver', None)
    if bool(source) == bool(receiver):
        return None
    partner = source if direction == 'incoming' else receiver
    if partner is None or getattr(partner, 'type', None) != 'user' or getattr(partner, 'transaction_type', None) != 'invoice_payment':
        return None
    amount = getattr(transaction, 'amount', None)
    fraction = getattr(transaction, 'nanostar_amount', None)
    user_id = getattr(getattr(partner, 'user', None), 'id', None)
    charge_id = getattr(transaction, 'id', None)
    if type(amount) is not int or not 1 <= amount <= 10000:
        return None
    if fraction is not None and (type(fraction) is not int or fraction != 0):
        return None
    if type(user_id) is not int or not 0 < user_id < 2**63:
        return None
    if not isinstance(charge_id, str) or not 1 <= len(charge_id.encode('utf-8')) <= 255:
        return None
    payload = getattr(partner, 'invoice_payload', None)
    matched = re.fullmatch(r'sband_stars:([0-9a-f]{32})', payload) if isinstance(payload, str) else None
    if matched:
        invoice_id = matched.group(1)
    elif direction == 'refund' and (payload is None or payload == ''):
        invoice_id = None
    else:
        return None
    return Entry(direction, user_id, invoice_id, amount, charge_id)


def _offset(value):
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal() or len(value) > 10:
        return 0
    return min(int(value), 2**31 - PAGE_SIZE)


async def _page(bot, offset):
    result = await asyncio.wait_for(bot.get_star_transactions(offset=offset, limit=PAGE_SIZE), timeout=20)
    items = getattr(result, 'transactions', None)
    if not isinstance(items, list) or len(items) > PAGE_SIZE:
        raise RuntimeError('Invalid Stars history response')
    return items


async def _apply_page(items, store, stats):
    # Refunds first prevent a recovered, already-refunded receipt ever restoring credit.
    for direction in ('refund', 'incoming'):
        for item in items:
            entry = _entry(item, direction)
            if entry is None:
                continue
            try:
                if direction == 'incoming':
                    await store.credit_payment(entry.user_id, entry.invoice_id, entry.stars, entry.charge_id)
                    stats['payments'] += 1
                else:
                    if entry.invoice_id is None:
                        known = await store.charge_info(entry.charge_id)
                        if not known:
                            # This trusted outgoing refund can precede the incoming page.
                            # The ledger records a no-money tombstone only for known users.
                            await store.record_unmatched_refund(entry.user_id, entry.stars, entry.charge_id)
                            stats['unmatched_refunds'] += 1
                            continue
                        if known['user_id'] != entry.user_id or known['stars'] != entry.stars:
                            raise ValueError('Refund correlation mismatch')
                    await store.refund_payment(entry.invoice_id, entry.stars, entry.charge_id, user_id=entry.user_id)
                    stats['refunds'] += 1
            except ValueError:
                # Validation failures cannot credit money and are revisited by full sweeps.
                # DB/API exceptions propagate, leaving the failed page checkpoint unchanged.
                stats['rejected'] += 1
                logger.warning('Stars history receipt rejected by ledger validation')


async def reconcile(bot, *, max_pages=MAX_PAGES):
    """Process a bounded history batch; DB/API failures do not advance that page."""
    if type(max_pages) is not int or not 2 <= max_pages <= 20:
        raise ValueError('History batch must contain 2–20 pages')
    store = _store()
    stats = {'pages': 0, 'payments': 0, 'refunds': 0, 'unmatched_refunds': 0, 'rejected': 0}
    offset = _offset(await db.get_setting(CURSOR_KEY, '0'))
    head = await _page(bot, 0)
    await _apply_page(head, store, stats)
    stats['pages'] += 1
    if len(head) < PAGE_SIZE:
        await db.set_setting(CURSOR_KEY, '0')
        return stats | {'offset': 0}
    if not offset:
        offset = PAGE_STEP
        await db.set_setting(CURSOR_KEY, str(offset))
    for _ in range(max_pages - 1):
        items = await _page(bot, offset)
        await _apply_page(items, store, stats)
        stats['pages'] += 1
        if len(items) < PAGE_SIZE:
            await db.set_setting(CURSOR_KEY, '0')
            return stats | {'offset': 0}
        offset += PAGE_STEP
        await db.set_setting(CURSOR_KEY, str(offset))
    return stats | {'offset': offset}


async def star_reconcile_worker(bot, *, interval=60):
    while True:
        delay = interval
        try:
            await reconcile(bot)
        except TelegramRetryAfter as exc:
            delay = max(delay, exc.retry_after)
            logger.warning('Stars history reconciliation paused by Telegram rate limit')
        except Exception:
            logger.warning('Stars history reconciliation deferred')
        await asyncio.sleep(delay)
