from contextlib import asynccontextmanager
import signal
import asyncio
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse

from logging_config import setup_logging
from routers.extract import router as extract_router
from routers.health import router as health_router
from routers.publish import router as publish_router
from routers.scheduled import router as scheduled_router
from routers.settings import router as settings_router
from routers.stats import router as stats_router
from routers.tasks import router as tasks_router
from routers.upload import router as upload_router
from schemas import error_response
from services.task_store import _tasks, TaskStatus, _persist_tasks, start_cleanup_loop
import structlog

logger = structlog.get_logger(__name__)
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    import sys

    def _handle_shutdown():
        logger.info("shutdown.received")
        for task in _tasks.values():
            if task.status == TaskStatus.PROCESSING:
                task.status = TaskStatus.INTERRUPTED
                task.finished_at = datetime.now(timezone.utc).isoformat()
        _persist_tasks()
        logger.info("shutdown.tasks_saved")

    if sys.platform != "win32":
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _handle_shutdown)
    else:
        import threading
        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)

        def _windows_handler(sig, frame):
            _handle_shutdown()
            signal.signal(sig, original_sigint if sig == signal.SIGINT else original_sigterm)

        signal.signal(signal.SIGINT, _windows_handler)
        signal.signal(signal.SIGTERM, _windows_handler)

    await start_cleanup_loop()

    from services.supabase_client import cleanup_stale_posts
    try:
        removed = await cleanup_stale_posts()
        if removed:
            logger.info("startup.cleanup", removed=removed)
    except Exception as exc:
        logger.warning("startup.cleanup_failed", error=str(exc))

    yield
    _handle_shutdown()


app = FastAPI(title="VK Post Scheduler", lifespan=lifespan)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(error=detail, code=str(exc.status_code)),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=500,
        content=error_response(error="Internal server error", code="500"),
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(extract_router, prefix="/api")
app.include_router(publish_router, prefix="/api")
app.include_router(scheduled_router, prefix="/api")
app.include_router(stats_router, prefix="/api")
app.include_router(tasks_router, prefix="/api")
app.include_router(upload_router, prefix="/api")


@app.get("/api/upload/media/{filename}")
async def serve_upload(filename: str):
    from routers.upload import UPLOAD_DIR
    filepath = UPLOAD_DIR / filename
    if not filepath.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(filepath)
