from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
import structlog

from config import COOKIES_PATH, MEDIA_DEGRADED_THRESHOLD, MEDIA_DEGRADED_WINDOW
from services.settings_store import get_settings

logger = structlog.get_logger(__name__)

TEMP_BASE = Path(tempfile.gettempdir()) / "vk_scheduler"
TEMP_BASE.mkdir(parents=True, exist_ok=True)

TWITTER_DOMAINS = {"twitter.com", "x.com", "t.co"}
TIKTOK_DOMAINS = {"tiktok.com", "vm.tiktok.com"}
_twitter_lock = asyncio.Lock()

_error_counts: dict[str, list[float]] = {}
DEGRADED_THRESHOLD = MEDIA_DEGRADED_THRESHOLD
DEGRADED_WINDOW = MEDIA_DEGRADED_WINDOW


def _domain_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _record_error(domain: str) -> None:
    now = time.time()
    if domain not in _error_counts:
        _error_counts[domain] = []
    _error_counts[domain].append(now)
    _error_counts[domain] = [t for t in _error_counts[domain] if now - t < DEGRADED_WINDOW]


def get_degraded_parsers() -> list[dict[str, Any]]:
    now = time.time()
    result = []
    for domain, timestamps in _error_counts.items():
        recent = [t for t in timestamps if now - t < DEGRADED_WINDOW]
        if len(recent) >= DEGRADED_THRESHOLD:
            result.append({
                "domain": domain,
                "error_count": len(recent),
                "since": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(min(recent))),
            })
    return result


def is_degraded() -> bool:
    return len(get_degraded_parsers()) > 0


def reset_error_counts() -> None:
    _error_counts.clear()


@dataclass
class MediaItem:
    id: str
    type: str
    thumbnail_url: Optional[str] = None
    original_url: Optional[str] = None
    selected: bool = True
    source_tool: str = "yt-dlp"


@dataclass
class ExtractResult:
    source_url: str
    media_items: list[MediaItem] = field(default_factory=list)
    error: Optional[str] = None
    already_used: bool = False


def _cookies_args() -> list[str]:
    if COOKIES_PATH.exists() and COOKIES_PATH.stat().st_size > 0:
        return ["--cookies", str(COOKIES_PATH)]
    return []


async def _run_process(cmd: list[str], timeout: int) -> tuple[str, str, int]:
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=5,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace"), proc.returncode
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        raise TimeoutError(f"Process timed out after {timeout}s")


def _parse_ytdlp_json(raw: str) -> list[dict[str, Any]]:
    entries = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _media_from_ytdlp(entries: list[dict[str, Any]], url: str) -> list[MediaItem]:
    items = []
    for i, entry in enumerate(entries):
        item_id = f"yt_{i}_{hash(url) & 0xFFFFFF:06x}"

        if entry.get("duration") and entry.get("duration", 0) > 0:
            thumbnail = entry.get("thumbnail") or ""
            formats = entry.get("formats", [])
            best_url = ""
            for fmt in formats:
                if fmt.get("vcodec", "none") != "none" and fmt.get("height", 0) and fmt["height"] <= 1080:
                    best_url = fmt.get("url", "")
                    break
            if not best_url:
                for fmt in reversed(formats):
                    if fmt.get("url"):
                        best_url = fmt["url"]
                        break
            items.append(MediaItem(
                id=item_id,
                type="video",
                thumbnail_url=thumbnail,
                original_url=entry.get("webpage_url") or url,
                selected=True,
                source_tool="yt-dlp",
            ))
        else:
            url_val = entry.get("webpage_url") or entry.get("url") or url
            thumbnail = entry.get("thumbnail") or url_val
            items.append(MediaItem(
                id=item_id,
                type="photo",
                thumbnail_url=thumbnail,
                original_url=url_val,
                selected=True,
                source_tool="yt-dlp",
            ))

    if not items:
        thumbnail = entries[0].get("thumbnail", "") if entries else ""
        url_val = entries[0].get("webpage_url") or entries[0].get("url", "") or url
        items.append(MediaItem(
            id=f"yt_0_{hash(url) & 0xFFFFFF:06x}",
            type="photo",
            thumbnail_url=thumbnail or url_val,
            original_url=url_val,
            selected=True,
            source_tool="yt-dlp",
        ))

    return items


def _media_from_gallerydl(entries: list[Any], url: str) -> list[MediaItem]:
    items = []
    for i, entry in enumerate(entries):
        item_id = f"gdl_{i}_{hash(url) & 0xFFFFFF:06x}"
        file_url = ""

        if isinstance(entry, (list, tuple)):
            if len(entry) >= 3 and entry[0] == 3:
                file_url = entry[1] if isinstance(entry[1], str) else ""
            elif len(entry) >= 2 and isinstance(entry[1], dict):
                file_url = entry[1].get("url", "")
                if not file_url and isinstance(entry[0], str):
                    file_url = entry[0]
        elif isinstance(entry, dict):
            file_url = entry.get("url", "") or entry.get("image_url", "")

        if file_url:
            ext = file_url.lower().split("?")[0]
            is_video = any(ext.endswith(e) for e in (".mp4", ".mov", ".webm", ".m3u8"))
            items.append(MediaItem(
                id=item_id,
                type="video" if is_video else "photo",
                thumbnail_url=file_url,
                original_url=file_url,
                selected=True,
                source_tool="gallery-dl",
            ))

    return items


async def _extract_ytdlp(url: str, timeout: int) -> tuple[list[dict[str, Any]], bool]:
    cmd = [sys.executable, "-m", "yt_dlp", "--dump-json", "--no-download", "--flat-playlist"] + _cookies_args() + [url]
    logger.info("extract.ytdlp.start", url=url)
    stdout, stderr, rc = await _run_process(cmd, timeout)

    if rc != 0:
        error_text = stderr.lower()
        if "unsupported" in error_text or "extractorerror" in error_text or "no suitable" in error_text:
            raise UnsupportedByTool("yt-dlp", url, stderr)
        raise RuntimeError(f"yt-dlp failed (rc={rc}): {stderr[:500]}")

    return _parse_ytdlp_json(stdout), True


async def _extract_gallerydl(url: str, timeout: int) -> list[Any]:
    cmd = [sys.executable, "-m", "gallery_dl", "--dump-json"] + _cookies_args() + [url]
    logger.info("extract.gallerydl.start", url=url)
    stdout, stderr, rc = await _run_process(cmd, timeout)

    if rc != 0:
        raise RuntimeError(f"gallery-dl failed (rc={rc}): {stderr[:500]}")

    try:
        data = json.loads(stdout)
        if isinstance(data, list):
            return data
        return [data]
    except json.JSONDecodeError:
        entries = []
        for line in stdout.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries


async def _try_direct_link(url: str, timeout: int) -> list[MediaItem]:
    logger.info("extract.direct_link", url=url)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.head(url)
            content_type = resp.headers.get("content-type", "")

            if resp.status_code >= 400:
                resp = await client.get(url, follow_redirects=True)
                content_type = resp.headers.get("content-type", "")

            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}")

            if "image" in content_type or "video" in content_type:
                media_type = "video" if "video" in content_type else "photo"
                return [MediaItem(
                    id=f"direct_{hash(url) & 0xFFFFFF:06x}",
                    type=media_type,
                    thumbnail_url=url,
                    original_url=url,
                    selected=True,
                    source_tool="httpx",
                )]
            else:
                raise RuntimeError(f"Not a media file (content-type: {content_type})")

    except Exception as exc:
        raise RuntimeError(f"Direct link failed: {exc}") from exc


class UnsupportedByTool(Exception):
    def __init__(self, tool: str, url: str, detail: str = ""):
        self.tool = tool
        self.url = url
        self.detail = detail
        super().__init__(f"{tool} does not support {url}")


async def extract_media(url: str) -> ExtractResult:
    settings = await get_settings()
    timeout = settings.get("ytdlp_timeout_seconds", 30)
    domain = _domain_from_url(url)

    result = ExtractResult(source_url=url)

    if is_twitter_url(url):
        async with _twitter_lock:
            try:
                entries = await _extract_gallerydl(url, timeout)
                result.media_items = _media_from_gallerydl(entries, url)
                logger.info("extract.gallerydl.twitter", url=url, count=len(result.media_items))
            except Exception as exc:
                logger.warning("extract.gallerydl.twitter_error", url=url, error=str(exc))

            if not result.media_items:
                try:
                    entries, _ = await _extract_ytdlp(url, timeout)
                    result.media_items = _media_from_ytdlp(entries, url)
                    logger.info("extract.ytdlp.twitter_fallback", url=url, count=len(result.media_items))
                except Exception as exc:
                    logger.warning("extract.ytdlp.twitter_error", url=url, error=str(exc))

            if not result.media_items:
                result.error = "Не удалось извлечь медиа из Twitter"

            await asyncio.sleep(3)
            return result

    try:
        entries, _ = await _extract_ytdlp(url, timeout)
        result.media_items = _media_from_ytdlp(entries, url)
        logger.info("extract.ytdlp.success", url=url, count=len(result.media_items))
        return result
    except UnsupportedByTool:
        logger.info("extract.ytdlp.unsupported", url=url, domain=domain)
        _record_error(domain)
    except TimeoutError:
        result.error = "Превышено время ожидания при извлечении медиа"
        _record_error(domain)
        return result
    except Exception as exc:
        logger.warning("extract.ytdlp.error", url=url, error=str(exc))
        _record_error(domain)

    try:
        entries = await _extract_gallerydl(url, timeout)
        result.media_items = _media_from_gallerydl(entries, url)
        logger.info("extract.gallerydl.success", url=url, count=len(result.media_items))
        return result
    except TimeoutError:
        result.error = "Превышено время ожидания при извлечении медиа (gallery-dl)"
        _record_error(domain)
        return result
    except Exception as exc:
        logger.warning("extract.gallerydl.error", url=url, error=str(exc))
        _record_error(domain)

    try:
        result.media_items = await _try_direct_link(url, timeout)
        logger.info("extract.direct.success", url=url)
        return result
    except Exception as exc:
        logger.warning("extract.direct.error", url=url, error=str(exc))
        result.error = f"Не удалось извлечь медиа: {exc}"
        return result


def is_twitter_url(url: str) -> bool:
    return _domain_from_url(url) in TWITTER_DOMAINS


def is_tiktok_url(url: str) -> bool:
    return _domain_from_url(url) in TIKTOK_DOMAINS


async def download_media_file(
    media_item: MediaItem,
    task_id: str,
    max_size_mb: int,
) -> Optional[Path]:
    task_dir = TEMP_BASE / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    url = media_item.original_url or ""
    ext = _guess_extension(url, media_item.type)
    filename = f"{media_item.id}{ext}"
    filepath = task_dir / filename

    settings = await get_settings()
    timeout = settings.get("ytdlp_timeout_seconds", 60)

    if is_twitter_url(url) or is_tiktok_url(url):
        return await _download_ytdlp(url, filepath, timeout, max_size_mb)

    if url.startswith("http://") or url.startswith("https://"):
        result = await _download_httpx(url, filepath, timeout, max_size_mb)
        if result:
            return result

    if media_item.source_tool == "yt-dlp":
        return await _download_ytdlp(url, filepath, timeout, max_size_mb)
    elif media_item.source_tool == "gallery-dl":
        return await _download_gallerydl(url, filepath, timeout, max_size_mb)

    return await _download_httpx(url, filepath, timeout, max_size_mb)


def _guess_extension(url: str, media_type: str) -> str:
    for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov", ".webm"):
        if ext in url.lower():
            return ext
    return ".mp4" if media_type == "video" else ".jpg"


async def _download_ytdlp(url: str, filepath: Path, timeout: int, max_size_mb: int) -> Optional[Path]:
    settings = await get_settings()
    max_workers = settings.get("max_download_workers", 3)
    if is_twitter_url(url):
        max_workers = 1

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "--no-playlist",
        "-o", str(filepath),
    ] + _cookies_args() + [url]

    logger.info("download.ytdlp.start", url=url, path=str(filepath))
    try:
        _, stderr, rc = await _run_process(cmd, timeout * 2)
        if rc != 0:
            logger.error("download.ytdlp.failed", url=url, stderr=stderr[:300])
            return None

        actual = _find_downloaded_file(filepath)
        if actual and actual.stat().st_size > max_size_mb * 1024 * 1024:
            actual.unlink(missing_ok=True)
            logger.warning("download.file_too_large", url=url, size=actual.stat().st_size)
            return None
        return actual
    except TimeoutError:
        logger.error("download.ytdlp.timeout", url=url)
        return None


async def _download_gallerydl(url: str, filepath: Path, timeout: int, max_size_mb: int) -> Optional[Path]:
    cmd = [sys.executable, "-m", "gallery_dl", "-d", str(filepath.parent)] + _cookies_args() + [url]

    logger.info("download.gallerydl.start", url=url)
    try:
        _, stderr, rc = await _run_process(cmd, timeout * 2)
        if rc != 0:
            logger.error("download.gallerydl.failed", url=url, stderr=stderr[:300])
            return None

        actual = _find_downloaded_file(filepath.parent)
        if actual and actual.stat().st_size > max_size_mb * 1024 * 1024:
            actual.unlink(missing_ok=True)
            return None
        return actual
    except TimeoutError:
        logger.error("download.gallerydl.timeout", url=url)
        return None


async def _download_httpx(url: str, filepath: Path, timeout: int, max_size_mb: int) -> Optional[Path]:
    logger.info("download.httpx.start", url=url)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    logger.error("download.httpx.error", url=url, status=resp.status_code)
                    return None

                size = 0
                max_bytes = max_size_mb * 1024 * 1024
                with open(filepath, "wb") as f:
                    async for chunk in resp.aiter_bytes(8192):
                        size += len(chunk)
                        if size > max_bytes:
                            f.close()
                            filepath.unlink(missing_ok=True)
                            logger.warning("download.httpx.too_large", url=url)
                            return None
                        f.write(chunk)

        return filepath
    except Exception as exc:
        logger.error("download.httpx.failed", url=url, error=str(exc))
        return None


def _find_downloaded_file(path: Path) -> Optional[Path]:
    if path.exists() and path.is_file():
        return path

    if path.parent.exists():
        candidates = sorted(path.parent.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        for c in candidates:
            if c.is_file() and c.suffix in (".mp4", ".mkv", ".webm", ".jpg", ".jpeg", ".png", ".gif", ".webp"):
                return c
    return None


async def cleanup_old_temp_dirs(max_age_hours: int = 24) -> int:
    now = time.time()
    removed = 0
    if not TEMP_BASE.exists():
        return 0

    for d in TEMP_BASE.iterdir():
        if d.is_dir():
            age = now - d.stat().st_mtime
            if age > max_age_hours * 3600:
                try:
                    import shutil
                    shutil.rmtree(d)
                    removed += 1
                except Exception as exc:
                    logger.warning("cleanup.failed", path=str(d), error=str(exc))

    if removed:
        logger.info("cleanup.removed", count=removed)
    return removed
