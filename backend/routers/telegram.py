from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import telegram_api
from services.settings_store import get_settings, update_settings

router = APIRouter(tags=["telegram"])


class AuthStartRequest(BaseModel):
    phone: str


class AuthCompleteRequest(BaseModel):
    code: str
    phone_code_hash: str


class AuthPasswordRequest(BaseModel):
    password: str


class AuthResendRequest(BaseModel):
    phone: str
    phone_code_hash: str


class ChannelSelectRequest(BaseModel):
    channel_id: int
    channel_title: str


@router.get("/telegram/status")
async def telegram_status():
    return await telegram_api.get_status()


@router.post("/telegram/auth/start")
async def telegram_auth_start(body: AuthStartRequest):
    try:
        result = await telegram_api.start_auth(body.phone)
        return {"status": "code_sent", **result}
    except telegram_api.TelegramError as exc:
        raise HTTPException(400, str(exc))


@router.post("/telegram/auth/resend")
async def telegram_auth_resend(body: AuthResendRequest):
    try:
        result = await telegram_api.resend_code(body.phone, body.phone_code_hash)
        return {"status": "code_sent", **result}
    except telegram_api.TelegramError as exc:
        raise HTTPException(400, str(exc))


@router.post("/telegram/auth/complete")
async def telegram_auth_complete(body: AuthCompleteRequest):
    try:
        result = await telegram_api.complete_auth(body.code, body.phone_code_hash)
        return result
    except telegram_api.TelegramError as exc:
        raise HTTPException(400, str(exc))


@router.post("/telegram/auth/password")
async def telegram_auth_password(body: AuthPasswordRequest):
    try:
        result = await telegram_api.complete_auth_password(body.password)
        return result
    except telegram_api.TelegramError as exc:
        raise HTTPException(400, str(exc))


@router.get("/telegram/channels")
async def telegram_channels():
    return await telegram_api.get_channels()


@router.post("/telegram/channels/select")
async def telegram_select_channel(body: ChannelSelectRequest):
    await update_settings({
        "tg_channel_id": body.channel_id,
        "tg_channel_title": body.channel_title,
    })
    from routers.stats import reset_tg_photos_cache
    reset_tg_photos_cache()
    return {"status": "ok", "channel_id": body.channel_id, "channel_title": body.channel_title}


@router.get("/telegram/scheduled")
async def telegram_scheduled():
    settings = await get_settings()
    channel = settings.get("tg_channel_id")
    if not channel:
        return []
    return await telegram_api.get_scheduled(channel)


@router.delete("/telegram/scheduled/{message_id}")
async def telegram_delete_scheduled(message_id: int):
    settings = await get_settings()
    channel = settings.get("tg_channel_id")
    if not channel:
        raise HTTPException(400, "Telegram channel not configured")
    try:
        await telegram_api.delete_scheduled(channel, [message_id])
        return {"status": "ok"}
    except Exception as exc:
        raise HTTPException(500, f"Failed to delete: {exc}")
