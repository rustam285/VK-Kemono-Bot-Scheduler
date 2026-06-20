from __future__ import annotations

import asyncio
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import structlog
from telethon import TelegramClient
from telethon.errors import (
    AuthKeyError,
    FloodWaitError,
    SessionPasswordNeededError,
)
from telethon.tl.types import Channel

from config import TG_API_HASH, TG_API_ID, TG_PROXY, TG_SESSION_PATH

logger = structlog.get_logger(__name__)

_client: Optional[TelegramClient] = None
_client_lock = asyncio.Lock()
_initialized = False

_scheduled_cache: dict[str, tuple[float, list]] = {}
_SCHEDULED_CACHE_TTL = 30

_channel_title_cache: dict[str, str] = {}

TG_RETRY_DELAYS = [1, 4, 16]
TG_MAX_RETRIES = 3

def _generate_device_kwargs() -> dict[str, str]:
    models = ["Desktop", "PC", "Laptop", "Workstation"]
    versions = ["Windows 10", "Windows 11", "Linux", "macOS"]
    return {
        "device_model": random.choice(models),
        "system_version": random.choice(versions),
        "app_version": f"{random.randint(1, 5)}.{random.randint(0, 9)}.{random.randint(0, 9)}",
        "lang_code": "ru",
        "system_lang_code": "ru-RU",
    }


TG_DEVICE_KWARGS = _generate_device_kwargs()


def _normalize_channel_id(channel: str | int) -> int:
    cid = int(channel)
    if cid > 0:
        return int(f"-100{cid}")
    return cid


class TelegramError(Exception):
    pass


class TelegramNotConfigured(TelegramError):
    pass


class TelegramSessionExpired(TelegramError):
    pass


def _is_configured() -> bool:
    return TG_API_ID != 0 and bool(TG_API_HASH)


def _parse_proxy(proxy_url: str):
    if not proxy_url:
        return None
    try:
        from urllib.parse import urlparse
        parsed = urlparse(proxy_url)
        scheme = parsed.scheme.lower()
        host = parsed.hostname
        port = parsed.port or 1080
        username = parsed.username
        password = parsed.password

        if scheme in ("socks5", "socks"):
            try:
                import socks
                return (socks.SOCKS5, host, port, True, username, password)
            except ImportError:
                logger.warning("telegram.proxy_requires_pysocks")
                return None
        elif scheme in ("http", "https"):
            try:
                import socks
                return (socks.HTTP, host, port, True, username, password)
            except ImportError:
                logger.warning("telegram.proxy_requires_pysocks")
                return None
        else:
            logger.warning("telegram.unsupported_proxy_scheme", scheme=scheme)
            return None
    except Exception as exc:
        logger.warning("telegram.proxy_parse_failed", error=str(exc))
        return None


async def _create_client() -> TelegramClient:
    proxy = _parse_proxy(TG_PROXY)
    if proxy:
        logger.info("telegram.proxy_configured", type=proxy[0])
    return TelegramClient(
        str(TG_SESSION_PATH), TG_API_ID, TG_API_HASH,
        proxy=proxy,
        **TG_DEVICE_KWARGS,
    )


async def init_client() -> None:
    global _client, _initialized
    if not _is_configured():
        logger.warning("telegram.not_configured")
        return

    if _client is not None and _initialized:
        return

    _client = await _create_client()

    try:
        await _client.connect()
        if await _client.is_user_authorized():
            try:
                await _client.get_dialogs()
            except Exception as exc:
                logger.warning("telegram.get_dialogs_failed", error=str(exc))
            _initialized = True
            logger.info("telegram.initialized")
        else:
            _initialized = True
            logger.info("telegram.connected_not_authorized")
    except AuthKeyError:
        logger.warning("telegram.session_expired_on_init")
        _initialized = True
        try:
            os.remove(str(TG_SESSION_PATH))
            logger.info("telegram.session_file_deleted")
        except OSError:
            pass
    except Exception as exc:
        logger.warning("telegram.init_failed", error=str(exc))
        _initialized = True


def _ensure_client() -> TelegramClient:
    if _client is None:
        raise TelegramNotConfigured("Telegram client not initialized")
    return _client


async def is_authorized() -> bool:
    async with _client_lock:
        client = _ensure_client()
        try:
            return await client.is_user_authorized()
        except AuthKeyError:
            return False
        except Exception:
            return False


async def get_me() -> Optional[dict]:
    async with _client_lock:
        client = _ensure_client()
        if not await client.is_user_authorized():
            return None
        try:
            me = await client.get_me()
            return {
                "id": me.id,
                "first_name": me.first_name,
                "last_name": me.last_name or "",
                "phone": me.phone or "",
                "username": me.username or "",
            }
        except Exception as exc:
            logger.error("telegram.get_me_failed", error=str(exc))
            return None


async def get_status() -> dict:
    if not _is_configured():
        return {"status": "not_configured", "account": None}

    async with _client_lock:
        client = _ensure_client()
        try:
            authorized = await client.is_user_authorized()
        except AuthKeyError:
            return {"status": "session_expired", "account": None}
        except Exception:
            return {"status": "not_authorized", "account": None}

        if not authorized:
            return {"status": "not_authorized", "account": None}

        try:
            me = await client.get_me()
            return {
                "status": "authorized",
                "account": {
                    "id": me.id,
                    "first_name": me.first_name,
                    "last_name": me.last_name or "",
                    "phone": me.phone or "",
                    "username": me.username or "",
                },
            }
        except Exception as exc:
            logger.error("telegram.get_status_failed", error=str(exc))
            return {"status": "not_authorized", "account": None}


async def start_auth(phone: str) -> dict:
    async with _client_lock:
        client = _ensure_client()
        logger.info("telegram.auth.start", phone=phone[:4] + "****")
        try:
            result = await client.send_code_request(phone)
            next_type = type(result.next_type).__name__ if result.next_type else "None"
            logger.info("telegram.auth.code_sent",
                        phone_code_hash=result.phone_code_hash[:10] + "...",
                        code_type=type(result.type).__name__,
                        next_type=next_type)
            return {
                "phone_code_hash": result.phone_code_hash,
                "code_type": type(result.type).__name__,
                "next_type": next_type,
            }
        except FloodWaitError as e:
            raise TelegramError(f"Telegram flood wait: {e.seconds} seconds. Try again after {e.seconds}s.")
        except Exception as exc:
            logger.error("telegram.start_auth_failed", error=str(exc))
            raise TelegramError(f"Failed to send auth code: {exc}")


async def resend_code(phone: str, phone_code_hash: str) -> dict:
    async with _client_lock:
        client = _ensure_client()
        logger.info("telegram.auth.resend", phone=phone[:4] + "****")
        try:
            from telethon.tl.functions.auth import ResendCodeRequest
            result = await client(ResendCodeRequest(phone_number=phone, phone_code_hash=phone_code_hash))
            next_type = type(result.next_type).__name__ if result.next_type else "None"
            logger.info("telegram.auth.resend_sent",
                        code_type=type(result.type).__name__,
                        next_type=next_type)
            return {
                "phone_code_hash": result.phone_code_hash,
                "code_type": type(result.type).__name__,
                "next_type": next_type,
            }
        except FloodWaitError as e:
            raise TelegramError(f"Flood wait: {e.seconds} seconds")
        except Exception as exc:
            logger.error("telegram.resend_failed", error=str(exc))
            raise TelegramError(f"Resend failed: {exc}")


async def complete_auth(code: str, phone_code_hash: str) -> dict:
    async with _client_lock:
        client = _ensure_client()
        try:
            await client.sign_in(code=code, phone_code_hash=phone_code_hash)
            return {"status": "ok"}
        except SessionPasswordNeededError:
            return {"status": "password_required"}
        except Exception as exc:
            raise TelegramError(f"Auth failed: {exc}")


async def complete_auth_password(password: str) -> dict:
    async with _client_lock:
        client = _ensure_client()
        try:
            await client.sign_in(password=password)
            try:
                await client.get_dialogs()
            except Exception:
                pass
            return {"status": "ok"}
        except Exception as exc:
            raise TelegramError(f"Password auth failed: {exc}")


async def get_channels() -> list[dict]:
    async with _client_lock:
        client = _ensure_client()
        if not await client.is_user_authorized():
            return []
        try:
            channels = []
            async for dialog in client.iter_dialogs():
                if dialog.is_channel:
                    entity = dialog.entity
                    if isinstance(entity, Channel) and (entity.creator or entity.admin_rights):
                        channels.append({
                            "id": entity.id,
                            "title": entity.title,
                            "username": entity.username or "",
                            "access_hash": entity.access_hash,
                        })
            return channels
        except Exception as exc:
            logger.error("telegram.get_channels_failed", error=str(exc))
            return []


async def get_channel_title(channel_id: str | int) -> Optional[str]:
    ch = str(channel_id)
    if ch in _channel_title_cache:
        return _channel_title_cache[ch] or None
    try:
        async with _client_lock:
            client = _ensure_client()
            if not await client.is_user_authorized():
                return None
            entity_id = int(ch)
            if entity_id > 0:
                entity_id = int(f"-100{entity_id}")
            entity = await client.get_entity(entity_id)
            if hasattr(entity, "title"):
                _channel_title_cache[ch] = entity.title
                return entity.title
            _channel_title_cache[ch] = ""
            return None
    except Exception:
        _channel_title_cache[ch] = ""
        return None


async def get_scheduled(channel: str | int) -> list[dict]:
    cache_key = str(channel)
    now = time.time()
    if cache_key in _scheduled_cache:
        cached_at, cached_data = _scheduled_cache[cache_key]
        if now - cached_at < _SCHEDULED_CACHE_TTL:
            return cached_data

    async with _client_lock:
        client = _ensure_client()
        if not await client.is_user_authorized():
            return []
        try:
            entity = await client.get_entity(_normalize_channel_id(channel))
            messages = await client.get_messages(entity, scheduled=True)
            result = []
            for msg in messages:
                if msg is None:
                    continue
                result.append({
                    "id": msg.id,
                    "date": msg.date.isoformat() if msg.date else None,
                    "text": msg.text or "",
                    "has_media": msg.media is not None,
                })
            _scheduled_cache[cache_key] = (now, result)
            return result
        except FloodWaitError as e:
            logger.warning("telegram.get_scheduled_flood_wait", seconds=e.seconds)
            return []
        except Exception as exc:
            logger.error("telegram.get_scheduled_failed", channel=channel, error=str(exc))
            return []


def _invalidate_cache(channel: Optional[str] = None) -> None:
    if channel:
        _scheduled_cache.pop(str(channel), None)
    else:
        _scheduled_cache.clear()


async def _flood_wait_handler(func, *args, **kwargs):
    for attempt in range(TG_MAX_RETRIES):
        try:
            return await func(*args, **kwargs)
        except FloodWaitError as e:
            if e.seconds <= 300:
                logger.warning("telegram.flood_wait", seconds=e.seconds, attempt=attempt + 1)
                await asyncio.sleep(e.seconds)
                continue
            raise TelegramError(f"Telegram flood wait: {e.seconds} seconds")
    raise TelegramError("Failed after FloodWait retries")


async def send_scheduled(
    channel: str | int,
    text: str,
    media_files: list[Path],
    schedule_dt: datetime,
) -> list[int]:
    if not media_files:
        return await _flood_wait_handler(_send_text_scheduled, channel, text, schedule_dt)
    elif len(media_files) == 1:
        return await _flood_wait_handler(_send_single_media_scheduled, channel, text, media_files[0], schedule_dt)
    else:
        return await _flood_wait_handler(_send_album_scheduled, channel, text, media_files, schedule_dt)


async def _send_text_scheduled(
    channel: str | int,
    text: str,
    schedule_dt: datetime,
) -> list[int]:
    async with _client_lock:
        client = _ensure_client()
        entity = await client.get_entity(_normalize_channel_id(channel))
        msg = await client.send_message(entity, text, schedule=schedule_dt)
        _invalidate_cache(str(channel))
        return [msg.id]


async def _send_single_media_scheduled(
    channel: str | int,
    text: str,
    file: Path,
    schedule_dt: datetime,
) -> list[int]:
    async with _client_lock:
        client = _ensure_client()
        entity = await client.get_entity(_normalize_channel_id(channel))
        total_size = file.stat().st_size

        def _progress(current: int, total: int):
            pct = int(current * 100 / total) if total else 0
            if pct % 10 == 0:
                logger.info("telegram.upload_progress", current=current, total=total, pct=pct)

        msg = await client.send_file(entity, file, caption=text, schedule=schedule_dt, progress_callback=_progress)
        logger.info("telegram.upload_done", file=str(file), size=total_size)
        _invalidate_cache(str(channel))
        return [msg.id]


async def _send_album_scheduled(
    channel: str | int,
    text: str,
    files: list[Path],
    schedule_dt: datetime,
) -> list[int]:
    async with _client_lock:
        client = _ensure_client()
        entity = await client.get_entity(_normalize_channel_id(channel))

        def _progress(current: int, total: int):
            pct = int(current * 100 / total) if total else 0
            if pct % 10 == 0:
                logger.info("telegram.upload_progress", current=current, total=total, pct=pct)

        messages = await client.send_file(entity, files, caption=text, schedule=schedule_dt, progress_callback=_progress)
        logger.info("telegram.upload_done", count=len(files) if isinstance(files, list) else 1)
        _invalidate_cache(str(channel))
        if isinstance(messages, list):
            return [m.id for m in messages]
        return [messages.id]


async def delete_scheduled(channel: str | int, message_ids: list[int]) -> bool:
    async with _client_lock:
        client = _ensure_client()
        entity = await client.get_entity(_normalize_channel_id(channel))
        from telethon.tl.functions.messages import DeleteScheduledMessagesRequest
        try:
            await client(DeleteScheduledMessagesRequest(peer=entity, id=message_ids))
        except FloodWaitError as e:
            logger.warning("telegram.delete_flood_wait", seconds=e.seconds)
            await asyncio.sleep(e.seconds)
            await client(DeleteScheduledMessagesRequest(peer=entity, id=message_ids))
        _invalidate_cache(str(channel))
        return True
