from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

import pytz
import structlog

from services.settings_store import get_settings
from services.vk_api import VkApiError, call_method

logger = structlog.get_logger(__name__)

_slot_cache: dict[str, dict[str, Any]] = {}
CACHE_TTL = 300


def _make_session_key() -> str:
    return str(uuid.uuid4())


def _get_cached_slots(session_key: str) -> Optional[set[datetime]]:
    entry = _slot_cache.get(session_key)
    if not entry:
        return None
    if time.time() > entry["expires_at"]:
        del _slot_cache[session_key]
        return None
    return entry["slots"]


def _set_cached_slots(session_key: str, slots: set[datetime]) -> None:
    _slot_cache[session_key] = {
        "slots": slots,
        "expires_at": time.time() + CACHE_TTL,
    }


def invalidate_cache(session_key: Optional[str] = None) -> None:
    if session_key:
        _slot_cache.pop(session_key, None)
    else:
        _slot_cache.clear()


async def fetch_occupied_slots_from_vk(group_id: int) -> set[datetime]:
    occupied: set[datetime] = set()
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
            logger.warning("scheduler.vk_wall_get_failed", error=str(exc))
            break

        items = result.get("items", []) if isinstance(result, dict) else []
        for item in items:
            pub_date = item.get("publish_date")
            if pub_date:
                occupied.add(datetime.fromtimestamp(pub_date, tz=pytz.UTC))

        if len(items) < count:
            break
        offset += count

    logger.info("scheduler.fetched_occupied", count=len(occupied))
    return occupied


async def get_occupied_slots(
    session_key: Optional[str],
    group_id: int,
) -> tuple[str, set[datetime]]:
    if session_key:
        cached = _get_cached_slots(session_key)
        if cached is not None:
            logger.debug("scheduler.cache_hit", session_key=session_key, count=len(cached))
            return session_key, cached

    new_key = session_key or _make_session_key()
    occupied = await fetch_occupied_slots_from_vk(group_id)
    _set_cached_slots(new_key, occupied)
    return new_key, occupied


def assign_slots(
    post_count: int,
    start_date: str,
    time_slots: list[str],
    timezone_name: str,
    occupied: set[datetime],
) -> list[datetime]:
    tz = pytz.timezone(timezone_name)
    start = datetime.strptime(start_date, "%Y-%m-%d").date()

    schedule: list[datetime] = []
    current_date = start
    max_iterations = post_count * 10
    iteration = 0

    while len(schedule) < post_count and iteration < max_iterations:
        iteration += 1
        for slot_time in time_slots:
            if len(schedule) >= post_count:
                break

            hour, minute = map(int, slot_time.split(":"))
            naive_dt = datetime(current_date.year, current_date.month, current_date.day, hour, minute)
            aware_dt = tz.localize(naive_dt)

            if aware_dt not in occupied and aware_dt not in schedule:
                schedule.append(aware_dt)

        current_date += timedelta(days=1)

    return schedule


def build_post_text(post_type: str, url: str) -> str:
    hashtag = f"#{post_type}@xkemonox"
    if not url or url.startswith("local:"):
        return f"✯ {hashtag} ✯"
    return f"✯ {hashtag} ✯\n\nSource: {url}"


async def generate_preview(
    post_groups: list[dict[str, Any]],
    post_type: str,
    start_date: str,
    time_slots: list[str],
    timezone_name: str,
    session_key: Optional[str],
) -> tuple[str, list[dict[str, Any]]]:
    settings = await get_settings()
    group_id = settings.get("vk_group_id")
    if not group_id:
        raise ValueError("VK Group ID is not configured")

    session_key, occupied = await get_occupied_slots(session_key, group_id)
    schedule = assign_slots(len(post_groups), start_date, time_slots, timezone_name, occupied)

    posts = []
    for i, group in enumerate(post_groups):
        source_urls = group.get("source_urls", [])
        media_item_ids = group.get("media_item_ids", [])

        first_url = source_urls[0] if source_urls else ""
        post_text = build_post_text(post_type, first_url)

        post = {
            "id": str(uuid.uuid4()),
            "post_type": post_type,
            "scheduled_at": schedule[i].isoformat() if i < len(schedule) else None,
            "media_item_ids": media_item_ids,
            "post_text": post_text,
            "source_urls": source_urls,
        }
        posts.append(post)

    return session_key, posts
