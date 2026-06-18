from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import structlog
from supabase import Client, create_client

from config import SUPABASE_SERVICE_KEY, SUPABASE_URL
from services.url_utils import normalize_url

logger = structlog.get_logger(__name__)

_client: Optional[Client] = None
_lock = asyncio.Lock()
MAX_RETRIES = 3
RETRY_DELAY = 1


def _get_client(force: bool = False) -> Client:
    global _client
    if _client is None or force:
        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
        _client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    return _client


def _run_with_retry(fn, retries: int = MAX_RETRIES):
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            logger.warning("supabase.retry", attempt=attempt + 1, error=str(exc))
            if attempt < retries - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
                _get_client(force=True)
            else:
                raise


async def check_supabase_health() -> bool:
    def _ping():
        try:
            client = _get_client()
            client.table("used_urls").select("id").limit(1).execute()
            return True
        except Exception as exc:
            logger.warning("supabase.health_check_failed", error=str(exc))
            return False

    async with _lock:
        return await asyncio.to_thread(_ping)


async def check_url_used(url: str) -> bool:
    normalized = normalize_url(url)

    def _query():
        client = _get_client()
        result = client.table("used_urls").select("id").eq("normalized", normalized).limit(1).execute()
        return len(result.data) > 0

    async with _lock:
        return await asyncio.to_thread(_run_with_retry, _query)


async def check_urls_used(urls: list[str]) -> dict[str, bool]:
    if not urls:
        return {}

    norm_map = {normalize_url(u): u for u in urls}
    normalized_list = list(norm_map.keys())

    def _query():
        client = _get_client()
        result = client.table("used_urls").select("normalized").in_("normalized", normalized_list).execute()
        found = {row["normalized"] for row in result.data}
        return {u: normalize_url(u) in found for u in urls}

    async with _lock:
        return await asyncio.to_thread(_run_with_retry, _query)


async def record_used_url(url: str, vk_post_id: Optional[int] = None) -> None:
    normalized = normalize_url(url)

    def _insert():
        client = _get_client()
        client.table("used_urls").upsert(
            {"url": url, "normalized": normalized, "vk_post_id": vk_post_id},
            on_conflict="normalized",
        ).execute()

    async with _lock:
        await asyncio.to_thread(_run_with_retry, _insert)


async def insert_scheduled_post(post_data: dict[str, Any]) -> None:
    def _insert():
        client = _get_client()
        client.table("scheduled_posts").insert(post_data).execute()

    async with _lock:
        await asyncio.to_thread(_run_with_retry, _insert)


async def update_scheduled_post(vk_post_id: int, updates: dict[str, Any]) -> None:
    def _update():
        client = _get_client()
        client.table("scheduled_posts").update(updates).eq("vk_post_id", vk_post_id).execute()

    async with _lock:
        await asyncio.to_thread(_run_with_retry, _update)


async def get_scheduled_posts() -> list[dict[str, Any]]:
    def _query():
        client = _get_client()
        result = client.table("scheduled_posts").select("*").order("scheduled_at").execute()
        return result.data

    async with _lock:
        return await asyncio.to_thread(_run_with_retry, _query)


async def get_scheduled_post_by_vk_id(vk_post_id: int) -> Optional[dict[str, Any]]:
    def _query():
        client = _get_client()
        result = client.table("scheduled_posts").select("*").eq("vk_post_id", vk_post_id).limit(1).execute()
        return result.data[0] if result.data else None

    async with _lock:
        return await asyncio.to_thread(_run_with_retry, _query)


async def get_posts_without_media() -> list[dict[str, Any]]:
    def _query():
        client = _get_client()
        result = client.table("scheduled_posts").select("*").eq("has_media", False).neq("status", "deleted").order("scheduled_at").execute()
        return result.data

    async with _lock:
        return await asyncio.to_thread(_run_with_retry, _query)


async def cleanup_stale_posts() -> int:
    def _delete():
        client = _get_client()
        result = client.table("scheduled_posts").delete().in_("status", ["deleted", "error"]).execute()
        return len(result.data) if result.data else 0

    async with _lock:
        return await asyncio.to_thread(_run_with_retry, _delete)
