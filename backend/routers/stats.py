from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from services.settings_store import get_settings
from services.supabase_client import get_scheduled_posts
from services.vk_api import VkApiError, call_method

router = APIRouter(tags=["stats"])

_tg_photos_cache: dict[str, str] = {}
_tg_photos_loaded = False


def reset_tg_photos_cache() -> None:
    global _tg_photos_loaded
    _tg_photos_cache.clear()
    _tg_photos_loaded = False


async def _load_tg_photos() -> None:
    global _tg_photos_loaded
    if _tg_photos_loaded:
        return
    _tg_photos_loaded = True

    try:
        from services import telegram_api
        import base64

        async with telegram_api._client_lock:
            client = telegram_api._ensure_client()
            if not await client.is_user_authorized():
                return

            me_entity = await client.get_me()
            if me_entity and hasattr(me_entity, "photo") and me_entity.photo:
                try:
                    photo = await client.download_profile_photo(me_entity, file=bytes)
                    if photo:
                        _tg_photos_cache["account"] = "data:image/jpeg;base64," + base64.b64encode(photo).decode()
                except Exception:
                    pass

            settings = await get_settings()
            tg_channel = settings.get("tg_channel_id")
            if tg_channel:
                try:
                    from services.telegram_api import _normalize_channel_id
                    ch_entity = await client.get_entity(_normalize_channel_id(tg_channel))
                    if hasattr(ch_entity, "photo") and ch_entity.photo:
                        photo = await client.download_profile_photo(ch_entity, file=bytes)
                        if photo:
                            _tg_photos_cache["channel"] = "data:image/jpeg;base64," + base64.b64encode(photo).decode()
                except Exception:
                    pass
    except Exception:
        pass


@router.get("/stats")
async def get_stats():
    settings = await get_settings()
    group_id = settings.get("vk_group_id")
    owner_id = settings.get("vk_owner_id")
    tg_channel = settings.get("tg_channel_id")
    tg_channel_title = settings.get("tg_channel_title")

    account = None
    group = None

    if group_id and owner_id:
        try:
            user_data = await call_method("users.get", {
                "user_ids": str(owner_id),
                "fields": "photo_100",
            })
            u = user_data[0] if isinstance(user_data, list) else user_data
            account = {
                "id": u.get("id"),
                "name": f"{u.get('first_name', '')} {u.get('last_name', '')}".strip(),
                "photo_url": u.get("photo_100", ""),
            }
        except Exception:
            account = {"id": owner_id, "name": "Unknown", "photo_url": ""}

        try:
            group_resp = await call_method("groups.getById", {
                "group_id": str(group_id),
                "fields": "photo_100",
            })
            if isinstance(group_resp, dict) and "groups" in group_resp:
                g = group_resp["groups"][0]
            elif isinstance(group_resp, list):
                g = group_resp[0]
            else:
                g = group_resp
            group = {
                "id": g.get("id"),
                "name": g.get("name", ""),
                "photo_url": g.get("photo_100", ""),
            }
        except Exception:
            group = {"id": group_id, "name": "Unknown", "photo_url": ""}

    tg_account = None
    tg_channel_info = None

    await _load_tg_photos()

    try:
        from services import telegram_api
        tg_status = await telegram_api.get_status()
        if tg_status.get("status") == "authorized" and tg_status.get("account"):
            me = tg_status["account"]
            tg_account = {
                "id": me.get("id"),
                "name": f"{me.get('first_name', '')} {me.get('last_name', '')}".strip(),
                "username": me.get("username", ""),
                "photo_url": _tg_photos_cache.get("account", ""),
            }

        if tg_channel:
            tg_channel_info = {
                "id": tg_channel,
                "title": tg_channel_title or str(tg_channel),
                "photo_url": _tg_photos_cache.get("channel", ""),
            }
    except Exception:
        pass

    posts = await get_scheduled_posts()
    scheduled = [p for p in posts if p.get("status") == "scheduled"]

    vk_scheduled = [p for p in scheduled if p.get("platform") in ("vk", "both", None)]
    tg_scheduled = [p for p in scheduled if p.get("platform") in ("tg", "both")]

    total_scheduled = len(scheduled)
    vk_count = len(vk_scheduled)
    tg_count = len(tg_scheduled)

    last_post_datetime = None
    last_dense_date = None

    if scheduled:
        dates = []
        for p in scheduled:
            sa = p.get("scheduled_at")
            if sa:
                try:
                    dates.append(datetime.fromisoformat(sa.replace("Z", "+00:00")))
                except Exception:
                    pass

        if dates:
            last_post_datetime = max(dates).isoformat()

            date_counts: dict[str, int] = {}
            for d in dates:
                day = d.strftime("%Y-%m-%d")
                date_counts[day] = date_counts.get(day, 0) + 1

            dense_dates = [day for day, count in date_counts.items() if count >= 3]
            if dense_dates:
                last_dense_date = max(dense_dates)

    return {
        "total_scheduled": total_scheduled,
        "vk_scheduled": vk_count,
        "tg_scheduled": tg_count,
        "last_post_datetime": last_post_datetime,
        "last_dense_date": last_dense_date,
        "account": account,
        "group": group,
        "tg_account": tg_account,
        "tg_channel_info": tg_channel_info,
    }
