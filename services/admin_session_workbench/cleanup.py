"""Explicit deep cleanup. Never logs out clients or resets app authorizations."""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import List, Set, Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.functions.account import ResetWebAuthorizationsRequest, SetAccountTTLRequest, SetPrivacyRequest, UpdateProfileRequest, UpdateUsernameRequest
from telethon.tl.functions.channels import DeleteChannelRequest, LeaveChannelRequest
from telethon.tl.functions.contacts import BlockRequest, DeleteContactsRequest, GetContactsRequest, ResetSavedRequest
from telethon.tl.functions.messages import ClearAllDraftsRequest, DeleteChatUserRequest, DeleteHistoryRequest, GetAllStickersRequest, GetDialogFiltersRequest, UninstallStickerSetRequest, UpdateDialogFilterRequest
from telethon.tl.functions.payments import ClearSavedInfoRequest
from telethon.tl.functions.photos import DeletePhotosRequest, GetUserPhotosRequest
from telethon.tl.types import AccountDaysTTL, Channel, Chat, InputPhoto, InputPrivacyKeyChatInvite, InputPrivacyKeyForwards, InputPrivacyKeyPhoneCall, InputPrivacyKeyPhoneNumber, InputPrivacyKeyProfilePhoto, InputPrivacyKeyStatusTimestamp, InputPrivacyValueDisallowAll, InputStickerSetID, User

logger = logging.getLogger(__name__)

@dataclass
class CleanReport:
    profile_cleared: bool = False
    username_cleared: bool = False
    photos_deleted: int = 0
    contacts_deleted: int = 0
    saved_contacts_reset: bool = False
    folders_deleted: int = 0
    stickers_removed: int = 0
    channels_deleted: int = 0
    dialogs_purged: int = 0
    dialogs_failed: int = 0
    errors: List[str] = field(default_factory=list)
    saved_messages_cleared: bool = False
    privacy_secured: bool = False
    payments_cleared: bool = False
    ttl_set_30d: bool = False
    drafts_cleared: bool = False
    web_auths_reset: bool = False
    sessions_reset: bool = False
    sessions_reset_warning: Optional[str] = None

def render_progress_bar(current: int, total: int, length: int = 10) -> str:
    ratio = min(1.0, max(0.0, current / total)) if total > 0 else 0.0
    filled = int(length * ratio)
    return "█" * filled + "░" * (length - filled) + f" {int(ratio * 100)}%"

async def clean_account_dialogs(client: TelegramClient, reporter, report: CleanReport):
    """Clean a bounded number of dialogs concurrently, respecting account FloodWaits."""
    pending: Set[asyncio.Task] = set()
    blocked_until = 0.0
    loop = asyncio.get_running_loop()

    async def wait_for_account():
        while blocked_until > loop.time():
            await asyncio.sleep(blocked_until - loop.time())

    async def request(value):
        await wait_for_account()
        # Surface FloodWait to the shared account gate instead of sleeping per task.
        return await client(value, flood_sleep_threshold=0)

    async def clean_dialog(entity):
        nonlocal blocked_until
        if isinstance(entity, User) and getattr(entity, "is_self", False):
            return
        if not isinstance(entity, (Channel, Chat, User)):
            return
        for attempt in range(3):
            try:
                if isinstance(entity, Channel):
                    if getattr(entity, "creator", False):
                        try:
                            await request(DeleteChannelRequest(channel=entity))
                            report.channels_deleted += 1
                        except FloodWaitError:
                            raise
                        except Exception:
                            await request(LeaveChannelRequest(entity))
                    else:
                        await request(LeaveChannelRequest(entity))
                elif isinstance(entity, Chat):
                    await request(DeleteChatUserRequest(chat_id=entity.id, user_id="me"))
                else:
                    if getattr(entity, "bot", False):
                        try:
                            await request(BlockRequest(id=entity))
                        except FloodWaitError:
                            raise
                        except Exception:
                            pass
                    try:
                        await request(DeleteHistoryRequest(peer=entity, max_id=0, just_clear=False, revoke=True))
                    except FloodWaitError:
                        raise
                    except Exception:
                        await wait_for_account()
                        await client.delete_dialog(entity)
                report.dialogs_purged += 1
                if report.dialogs_purged % 10 == 0:
                    await reporter.update(
                        f"🧹 Очищено диалогов: <b>{report.dialogs_purged}</b>\n"
                        f"{render_progress_bar(8, 10)}"
                    )
                return
            except FloodWaitError as exc:
                blocked_until = max(blocked_until, loop.time() + exc.seconds + 1)
                await reporter.update(f"⏳ FloodWait: ожидание {exc.seconds} с...", force=True)
                if attempt < 2:
                    continue
            except Exception as exc:
                logger.warning("Не удалось очистить диалог %s: %s", entity.id, type(exc).__name__)
                break
        report.dialogs_failed += 1

    try:
        async for dialog in client.iter_dialogs():
            await wait_for_account()
            pending.add(asyncio.create_task(clean_dialog(dialog.entity)))
            if len(pending) >= 10:
                await asyncio.gather(*pending)
                pending.clear()
        if pending:
            await asyncio.gather(*pending)
    finally:
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

async def deep_clean_account(client: TelegramClient, reporter) -> CleanReport:
    report = CleanReport()

    # 1. Профиль и @username
    await reporter.update(f"🧹 Сброс профиля...\n{render_progress_bar(1, 10)}", force=True)
    try:
        await client(UpdateProfileRequest(first_name=".", last_name="", about=""))
        report.profile_cleared = True
    except FloodWaitError:
        raise
    except Exception as e:
        report.errors.append(type(e).__name__)
        logger.warning(f"Ошибка сброса профиля: {type(e).__name__}")

    try:
        me = await client.get_me()
        if getattr(me, "username", None):
            await client(UpdateUsernameRequest(username=""))
            report.username_cleared = True
    except FloodWaitError:
        raise
    except Exception as e:
        report.errors.append(type(e).__name__)
        logger.warning(f"Ошибка удаления username: {type(e).__name__}")

    # 2. Аватарки
    await reporter.update(f"🧹 Удаление фото профиля...\n{render_progress_bar(2, 10)}")
    try:
        photos = await client(GetUserPhotosRequest(user_id="me", offset=0, max_id=0, limit=200))
        if photos.photos:
            input_photos = [
                InputPhoto(id=p.id, access_hash=p.access_hash, file_reference=p.file_reference)
                for p in photos.photos
            ]
            await client(DeletePhotosRequest(id=input_photos))
            report.photos_deleted = len(input_photos)
    except FloodWaitError:
        raise
    except Exception as e:
        report.errors.append(type(e).__name__)
        logger.warning(f"Ошибка удаления фото: {type(e).__name__}")

    # 3. Privacy Lockdown
    await reporter.update(f"🔒 Сброс приватности...\n{render_progress_bar(3, 10)}")
    try:
        disallow = [InputPrivacyValueDisallowAll()]
        await client(SetPrivacyRequest(key=InputPrivacyKeyPhoneNumber(), rules=disallow))
        await client(SetPrivacyRequest(key=InputPrivacyKeyStatusTimestamp(), rules=disallow))
        await client(SetPrivacyRequest(key=InputPrivacyKeyProfilePhoto(), rules=disallow))
        await client(SetPrivacyRequest(key=InputPrivacyKeyForwards(), rules=disallow))
        await client(SetPrivacyRequest(key=InputPrivacyKeyPhoneCall(), rules=disallow))
        await client(SetPrivacyRequest(key=InputPrivacyKeyChatInvite(), rules=disallow))
        report.privacy_secured = True
    except FloodWaitError:
        raise
    except Exception as e:
        report.errors.append(type(e).__name__)
        logger.warning(f"Ошибка параметров приватности: {type(e).__name__}")

    # 4. Платежные реквизиты
    try:
        await client(ClearSavedInfoRequest(credentials=True, info=True))
        report.payments_cleared = True
    except FloodWaitError:
        raise
    except Exception as e:
        report.errors.append(type(e).__name__)
        logger.debug(f"Платежные данные отсутствуют: {type(e).__name__}")

    # 5. Установка TTL аккаунта (30 дней)
    try:
        await client(SetAccountTTLRequest(ttl=AccountDaysTTL(days=30)))
        report.ttl_set_30d = True
    except FloodWaitError:
        raise
    except Exception as e:
        report.errors.append(type(e).__name__)
        logger.debug(f"TTL не обновлен: {type(e).__name__}")

    # 6. Контакты и облачный поисковый граф
    await reporter.update(f"🧹 Стирание контактов...\n{render_progress_bar(4, 10)}")
    try:
        contacts_res = await client(GetContactsRequest(hash=0))
        users = getattr(contacts_res, "users", [])
        if users:
            await client(DeleteContactsRequest(id=users))
            report.contacts_deleted = len(users)
        await client(ResetSavedRequest())
        report.saved_contacts_reset = True
    except FloodWaitError:
        raise
    except Exception as e:
        report.errors.append(type(e).__name__)
        logger.warning(f"Ошибка удаления контактов: {type(e).__name__}")

    # 7. Папки чатов
    await reporter.update(f"🧹 Удаление папок...\n{render_progress_bar(5, 10)}")
    try:
        filters = await client(GetDialogFiltersRequest())
        for f in getattr(filters, "filters", []):
            fid = getattr(f, "id", None)
            if fid is not None and fid != 0:
                await client(UpdateDialogFilterRequest(id=fid, filter=None))
                report.folders_deleted += 1
    except FloodWaitError:
        raise
    except Exception as e:
        report.errors.append(type(e).__name__)
        logger.warning(f"Ошибка папок: {type(e).__name__}")

    # 8. Стикеры и эмодзи-паки
    try:
        stickers = await client(GetAllStickersRequest(hash=0))
        for sset in getattr(stickers, "sets", []):
            try:
                await client(UninstallStickerSetRequest(stickerset=InputStickerSetID(id=sset.id, access_hash=sset.access_hash)))
                report.stickers_removed += 1
            except FloodWaitError:
                raise
            except Exception:
                report.errors.append("Ошибка очистки")
                pass
    except FloodWaitError:
        raise
    except Exception as e:
        report.errors.append(type(e).__name__)
        logger.warning(f"Ошибка стикеров: {type(e).__name__}")

    # 9. Черновики и Избранное
    try:
        await client(ClearAllDraftsRequest())
        report.drafts_cleared = True
    except FloodWaitError:
        raise
    except Exception:
        report.errors.append("Ошибка очистки")
        pass

    try:
        await client(DeleteHistoryRequest(peer="me", max_id=0, just_clear=False, revoke=True))
        report.saved_messages_cleared = True
    except FloodWaitError:
        raise
    except Exception as e:
        report.errors.append(type(e).__name__)
        logger.warning(f"Очистка Избранного: {type(e).__name__}")

    # 10. Диалоги, каналы, группы и боты
    await reporter.update(f"🧹 Тотальная зачистка чатов...\n{render_progress_bar(7, 10)}", force=True)
    await clean_account_dialogs(client, reporter, report)

    try:
        await client(ResetWebAuthorizationsRequest())
        report.web_auths_reset = True
    except FloodWaitError:
        raise
    except Exception as e:
        report.errors.append(type(e).__name__)
        pass

    await reporter.update(f"✅ Финал очистки!\n{render_progress_bar(10, 10)}", force=True)
    return report
