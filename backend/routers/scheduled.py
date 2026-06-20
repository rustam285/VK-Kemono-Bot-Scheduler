from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services.settings_store import get_settings
from services.supabase_client import (
    get_posts_without_media,
    get_scheduled_post_by_vk_id,
    get_scheduled_posts,
    insert_scheduled_post,
    update_scheduled_post,
    update_scheduled_post_by_id,
)
from services.vk_api import VkApiError, call_method

router = APIRouter(prefix="/scheduled", tags=["scheduled"])

_sync_cache: Optional[tuple[float, list]] = None
_SYNC_CACHE_TTL = 3600
_sync_lock = asyncio.Lock()


def _invalidate_sync_cache() -> None:
    global _sync_cache
    _sync_cache = None


async def _sync_with_vk() -> list[dict[str, Any]]:
    global _sync_cache
    now = time.time()
    if _sync_cache is not None:
        cached_at, cached_data = _sync_cache
        if now - cached_at < _SYNC_CACHE_TTL:
            return cached_data

    async with _sync_lock:
        if _sync_cache is not None:
            cached_at, cached_data = _sync_cache
            if now - cached_at < _SYNC_CACHE_TTL:
                return cached_data

        import structlog
        _log = structlog.get_logger(__name__)

    settings = await get_settings()
    group_id = settings.get("vk_group_id")
    if not group_id:
        raise HTTPException(400, "VK Group ID is not configured")

    vk_posts: list[dict[str, Any]] = []
    offset = 0
    count = 100

    while True:
        try:
            result = await call_method("wall.get", {
                "owner_id": f"-{group_id}",
                "filter": "postponed",
                "offset": offset,
                "count": count,
            })
        except VkApiError as exc:
            raise HTTPException(502, f"VK API error: {exc.message}")

        items = result.get("items", []) if isinstance(result, dict) else []
        vk_posts.extend(items)
        if len(items) < count:
            break
        offset += count

    _log.info("sync.vk_fetched", count=len(vk_posts), with_date=sum(1 for p in vk_posts if p.get("date")))

    db_posts = await get_scheduled_posts()
    db_by_vk_id = {p["vk_post_id"]: p for p in db_posts if p.get("vk_post_id")}

    vk_ids = set()
    inserted = 0
    for vk_post in vk_posts:
        vk_id = vk_post.get("id")
        if not vk_id:
            continue
        vk_ids.add(vk_id)

        post_date = vk_post.get("date")
        if not post_date:
            continue

        if vk_id in db_by_vk_id:
            continue

        attachments = vk_post.get("attachments", [])
        has_media = any(a.get("type") in ("photo", "video") for a in attachments)

        source_urls = []
        text = vk_post.get("text", "")
        for line in text.split("\n"):
            if line.strip().startswith("Source:"):
                source_urls.append(line.strip().replace("Source:", "").strip())

        media_attachments = []
        for att in attachments:
            if att.get("type") == "photo":
                p = att.get("photo", {})
                media_attachments.append({
                    "type": "photo",
                    "owner_id": p.get("owner_id"),
                    "media_id": p.get("id"),
                })
            elif att.get("type") == "video":
                v = att.get("video", {})
                media_attachments.append({
                    "type": "video",
                    "owner_id": v.get("owner_id"),
                    "media_id": v.get("id"),
                })

        post_type = "art"
        for line in text.split("\n"):
            if "#fursuit" in line:
                post_type = "fursuit"
            elif "#video" in line:
                post_type = "video"

        try:
            await insert_scheduled_post({
                "vk_post_id": vk_id,
                "post_type": post_type,
                "scheduled_at": datetime.fromtimestamp(post_date).isoformat(),
                "source_urls": source_urls,
                "media_attachments": media_attachments,
                "post_text": text,
                "has_media": has_media,
                "status": "scheduled",
            })
            inserted += 1
            _log.info("sync.inserted", vk_id=vk_id, post_type=post_type)
        except Exception as exc:
            _log.error("sync.insert_failed", vk_id=vk_id, error=str(exc))

    for db_post in db_posts:
        if db_post.get("status") == "scheduled" and db_post.get("vk_post_id") and db_post["vk_post_id"] not in vk_ids:
            await update_scheduled_post(db_post["vk_post_id"], {"status": "deleted"})

    all_posts = await get_scheduled_posts()
    result = [p for p in all_posts if p.get("status") != "deleted"]

    from services.telegram_api import get_channel_title
    import asyncio as _asyncio
    tg_titles_cache: dict[str, str] = {}
    for p in result:
        if p.get("tg_channel") and not p.get("tg_channel_title"):
            ch = str(p["tg_channel"])
            if ch not in tg_titles_cache:
                title = await get_channel_title(ch)
                tg_titles_cache[ch] = title or ""
                await _asyncio.sleep(0.5)
            title = tg_titles_cache[ch]
            if title:
                p["tg_channel_title"] = title
                if p.get("vk_post_id"):
                    try:
                        await update_scheduled_post(p["vk_post_id"], {"tg_channel_title": title})
                    except Exception:
                        pass

    _log.info("sync.done", vk_count=len(vk_posts), inserted=inserted, result_count=len(result))
    _sync_cache = (time.time(), result)
    return result


@router.get("")
async def get_scheduled():
    return await _sync_with_vk()


@router.get("/calendar")
async def get_calendar(year: int = Query(...), month: int = Query(..., ge=1, le=12)):
    posts = await _sync_with_vk()

    calendar: dict[str, dict[str, int]] = {}
    for post in posts:
        sa = post.get("scheduled_at")
        if not sa:
            continue
        try:
            dt = datetime.fromisoformat(sa.replace("Z", "+00:00"))
        except Exception:
            continue
        if dt.year == year and dt.month == month:
            day_key = dt.strftime("%Y-%m-%d")
            if day_key not in calendar:
                calendar[day_key] = {"art": 0, "fursuit": 0, "video": 0, "total": 0}
            pt = post.get("post_type", "art")
            if pt in calendar[day_key]:
                calendar[day_key][pt] += 1
            calendar[day_key]["total"] += 1

    return {"year": year, "month": month, "days": calendar}


@router.get("/no-media")
async def get_no_media():
    return await get_posts_without_media()


@router.get("/{vk_post_id}")
async def get_post_detail(vk_post_id: int):
    post = await get_scheduled_post_by_vk_id(vk_post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    return post


class PostUpdate(BaseModel):
    scheduled_at: Optional[str] = None
    post_text: Optional[str] = None
    media_items: Optional[list[dict]] = None


async def _update_tg_post(post: dict, body: PostUpdate):
    import json as _json
    import tempfile
    from pathlib import Path
    from services import telegram_api

    tg_channel = post.get("tg_channel")
    tg_message_ids = post.get("tg_message_ids")
    if not tg_channel or not tg_message_ids:
        raise HTTPException(400, "TG post has no channel or message IDs")

    if isinstance(tg_message_ids, str):
        try:
            tg_message_ids = _json.loads(tg_message_ids)
        except (ValueError, TypeError):
            raise HTTPException(400, "Invalid tg_message_ids")

    new_text = body.post_text if body.post_text is not None else post.get("post_text", "")
    new_scheduled = body.scheduled_at or post.get("scheduled_at")

    try:
        from services.telegram_api import _normalize_channel_id
        channel_id = _normalize_channel_id(tg_channel)

        schedule_dt = None
        if new_scheduled:
            schedule_dt = datetime.fromisoformat(new_scheduled.replace("Z", "+00:00"))

        media_files: list[Path] = []
        async with telegram_api._client_lock:
            client = telegram_api._ensure_client()
            entity = await client.get_entity(channel_id)

            all_scheduled = await client.get_messages(entity, scheduled=True)
            id_set = set(int(mid) for mid in tg_message_ids)
            target_msgs = [m for m in all_scheduled if m and m.id in id_set]

            import structlog
            _log = structlog.get_logger(__name__)
            _log.info("tg_edit.found_scheduled", requested=tg_message_ids,
                       found=[m.id for m in target_msgs],
                       has_media=[(m.id, m.media is not None) for m in target_msgs])

            for msg in target_msgs:
                try:
                    if msg.media:
                        tmp_dir = Path(tempfile.mkdtemp(prefix="tg_edit_"))
                        fpath = await client.download_media(msg.media, file=str(tmp_dir))
                        if fpath:
                            media_files.append(Path(fpath))
                            _log.info("tg_edit.media_downloaded", msg_id=msg.id, path=str(fpath))
                        else:
                            _log.warning("tg_edit.download_returned_none", msg_id=msg.id)
                    else:
                        _log.warning("tg_edit.no_media_on_message", msg_id=msg.id)
                except Exception as exc:
                    _log.error("tg_edit.media_download_failed", msg_id=msg.id, error=str(exc))

            from telethon.tl.functions.messages import DeleteScheduledMessagesRequest
            await client(DeleteScheduledMessagesRequest(peer=entity, id=tg_message_ids))

            if media_files:
                if len(media_files) == 1:
                    msg = await client.send_file(
                        entity, media_files[0], caption=new_text, schedule=schedule_dt
                    )
                    new_ids = [msg.id]
                else:
                    msgs = await client.send_file(
                        entity, media_files, caption=new_text, schedule=schedule_dt
                    )
                    new_ids = [m.id for m in msgs] if isinstance(msgs, list) else [msgs.id]
            else:
                msg = await client.send_message(entity, new_text, schedule=schedule_dt)
                new_ids = [msg.id]

        for f in media_files:
            try:
                f.unlink(missing_ok=True)
                if f.parent.name.startswith("tg_edit_"):
                    import shutil
                    shutil.rmtree(f.parent, ignore_errors=True)
            except Exception:
                pass

        telegram_api._invalidate_cache(str(tg_channel))

        db_updates = {
            "post_text": new_text,
            "tg_message_ids": _json.dumps(new_ids),
        }
        if body.scheduled_at and body.scheduled_at != post.get("scheduled_at"):
            db_updates["scheduled_at"] = body.scheduled_at

        post_id = post.get("id")
        if post_id:
            await update_scheduled_post_by_id(post_id, db_updates)
        elif post.get("vk_post_id"):
            await update_scheduled_post(post["vk_post_id"], db_updates)

        _invalidate_sync_cache()
        return {"status": "ok", "new_tg_message_ids": new_ids}
    except Exception as exc:
        import structlog
        _log = structlog.get_logger(__name__)
        _log.error("scheduled.edit_tg_error", error=str(exc))
        raise HTTPException(500, f"TG edit failed: {exc}")


@router.put("/{vk_post_id}")
async def update_post(vk_post_id: int, body: PostUpdate):
    post = await get_scheduled_post_by_vk_id(vk_post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    return await _do_update(post, body)


@router.put("/by-id/{post_id}")
async def update_post_by_id(post_id: str, body: PostUpdate):
    all_posts = await get_scheduled_posts()
    post = next((p for p in all_posts if p.get("id") == post_id), None)
    if not post:
        raise HTTPException(404, "Post not found")
    return await _do_update(post, body)


async def _do_update(post: dict, body: PostUpdate):
    settings = await get_settings()
    group_id = settings.get("vk_group_id")
    vk_post_id = post.get("vk_post_id")
    platform = post.get("platform", "vk")

    if platform == "tg" and not vk_post_id:
        return await _update_tg_post(post, body)

    has_media_change = body.media_items is not None and body.media_items != post.get("media_attachments")

    if has_media_change:
        try:
            publish_date = None
            sa = body.scheduled_at or post.get("scheduled_at")
            if sa:
                dt = datetime.fromisoformat(sa.replace("Z", "+00:00"))
                publish_date = int(dt.timestamp())

            params: dict[str, Any] = {
                "owner_id": f"-{group_id}",
                "from_group": 1,
                "message": body.post_text or post.get("post_text", ""),
                "publish_date": publish_date,
            }

            attachments = []
            for mi in (body.media_items or []):
                att_type = mi.get("type", "photo")
                owner = mi.get("owner_id", f"-{group_id}")
                mid = mi.get("media_id")
                if mid:
                    attachments.append(f"{att_type}{owner}_{mid}")
            if attachments:
                params["attachments"] = ",".join(attachments)

            result = await call_method("wall.post", params)
            new_vk_id = result.get("post_id") if isinstance(result, dict) else None

            if new_vk_id:
                await call_method("wall.delete", {"owner_id": f"-{group_id}", "post_id": vk_post_id})

            updates = {
                "vk_post_id": new_vk_id,
                "post_text": body.post_text or post.get("post_text"),
                "scheduled_at": body.scheduled_at or post.get("scheduled_at"),
                "media_attachments": body.media_items,
                "has_media": len(body.media_items) > 0 if body.media_items else post.get("has_media"),
            }
            await update_scheduled_post(vk_post_id, {"status": "deleted"})
            await insert_scheduled_post({k: v for k, v in updates.items() if v is not None})
            return {"status": "ok", "new_vk_post_id": new_vk_id}

        except VkApiError as exc:
            raise HTTPException(502, f"VK API error: {exc.message}")
    else:
        try:
            existing_attachments = post.get("media_attachments")
            if existing_attachments:
                import json as _json
                if isinstance(existing_attachments, str):
                    try:
                        existing_attachments = _json.loads(existing_attachments)
                    except (ValueError, TypeError):
                        existing_attachments = None

            current_scheduled = post.get("scheduled_at")
            new_scheduled = body.scheduled_at or current_scheduled

            post_text = body.post_text if body.post_text is not None else post.get("post_text", "")

            att_strings = []
            if existing_attachments and isinstance(existing_attachments, list):
                for att in existing_attachments:
                    if isinstance(att, dict):
                        if att.get("attachment"):
                            att_strings.append(att["attachment"])
                        elif att.get("media_id"):
                            att_type = att.get("type", "photo")
                            owner = att.get("owner_id", f"-{group_id}")
                            att_strings.append(f"{att_type}{owner}_{att['media_id']}")

            is_future = False
            if new_scheduled:
                try:
                    dt = datetime.fromisoformat(new_scheduled.replace("Z", "+00:00"))
                    is_future = dt.timestamp() > datetime.now(dt.tzinfo).timestamp()
                except Exception:
                    pass

            if is_future:
                wall_params: dict[str, Any] = {
                    "owner_id": f"-{group_id}",
                    "from_group": 1,
                    "message": post_text,
                    "publish_date": int(dt.timestamp()),
                }
                if att_strings:
                    wall_params["attachments"] = ",".join(att_strings)

                await call_method("wall.delete", {"owner_id": f"-{group_id}", "post_id": vk_post_id})
                import asyncio
                await asyncio.sleep(1)
                result = await call_method("wall.post", wall_params)
                new_vk_id = result.get("post_id") if isinstance(result, dict) else None

                db_updates: dict[str, Any] = {
                    "vk_post_id": new_vk_id,
                    "post_text": post_text,
                    "scheduled_at": new_scheduled,
                    "post_type": post.get("post_type", "art"),
                    "source_urls": post.get("source_urls", []),
                    "media_attachments": existing_attachments,
                    "has_media": bool(att_strings),
                    "status": "scheduled",
                    "platform": post.get("platform", "vk"),
                    "tg_message_ids": post.get("tg_message_ids"),
                    "tg_channel": post.get("tg_channel"),
                    "tg_channel_title": post.get("tg_channel_title"),
                }
                await update_scheduled_post(vk_post_id, {"status": "deleted"})
                await insert_scheduled_post({k: v for k, v in db_updates.items() if v is not None})
                _invalidate_sync_cache()
                return {"status": "ok", "new_vk_post_id": new_vk_id}
            else:
                edit_params: dict[str, Any] = {"owner_id": f"-{group_id}", "post_id": vk_post_id, "message": post_text}
                if att_strings:
                    edit_params["attachments"] = ",".join(att_strings)

                await call_method("wall.edit", edit_params)

                db_updates = {"post_text": post_text}
                if new_scheduled and new_scheduled != current_scheduled:
                    db_updates["scheduled_at"] = new_scheduled
                await update_scheduled_post(vk_post_id, db_updates)
                _invalidate_sync_cache()
                return {"status": "ok"}

        except VkApiError as exc:
            import structlog
            _log = structlog.get_logger(__name__)
            _log.error("scheduled.edit_vk_error", vk_post_id=vk_post_id, code=exc.code, message=exc.message)
            raise HTTPException(502, f"VK API error {exc.code}: {exc.message}")
        except Exception as exc:
            import structlog
            _log = structlog.get_logger(__name__)
            _log.error("scheduled.edit_failed", vk_post_id=vk_post_id, error=str(exc))
            raise HTTPException(500, f"Edit failed: {exc}")


@router.delete("/{vk_post_id}")
async def delete_post(vk_post_id: int):
    post = await get_scheduled_post_by_vk_id(vk_post_id)
    if not post:
        raise HTTPException(404, "Post not found")

    if post.get("platform") != "tg":
        settings = await get_settings()
        group_id = settings.get("vk_group_id")
        try:
            await call_method("wall.delete", {"owner_id": f"-{group_id}", "post_id": vk_post_id})
        except VkApiError as exc:
            raise HTTPException(502, f"VK API error {exc.code}: {exc.message}")
        except Exception as exc:
            raise HTTPException(500, f"Delete failed: {exc}")

    await update_scheduled_post(vk_post_id, {"status": "deleted"})
    _invalidate_sync_cache()
    return {"status": "ok"}


@router.delete("/by-id/{post_id}")
async def delete_post_by_id(post_id: str):
    all_posts = await get_scheduled_posts()
    post = next((p for p in all_posts if p.get("id") == post_id), None)
    if not post:
        raise HTTPException(404, "Post not found")

    if post.get("platform") != "tg" and post.get("vk_post_id"):
        settings = await get_settings()
        group_id = settings.get("vk_group_id")
        try:
            await call_method("wall.delete", {"owner_id": f"-{group_id}", "post_id": post["vk_post_id"]})
        except Exception:
            pass

    await update_scheduled_post_by_id(post_id, {"status": "deleted"})
    _invalidate_sync_cache()
    return {"status": "ok"}
