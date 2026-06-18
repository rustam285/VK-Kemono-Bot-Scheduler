from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, File, UploadFile

from config import DATA_DIR

router = APIRouter(prefix="/upload", tags=["upload"])

UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov", ".webm"}


@router.post("/media")
async def upload_media(file: UploadFile = File(...)):
    ext = Path(file.filename or "file").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return {"error": f"File type {ext} not allowed"}

    file_id = str(uuid.uuid4())
    filename = f"{file_id}{ext}"
    filepath = UPLOAD_DIR / filename

    content = await file.read()
    filepath.write_bytes(content)

    return {
        "id": file_id,
        "filename": filename,
        "url": f"http://127.0.0.1:8000/api/upload/media/{filename}",
        "size": len(content),
        "type": "video" if ext in (".mp4", ".mov", ".webm") else "photo",
    }
