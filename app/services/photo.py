from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import get_settings
from app.logging import get_logger
from app.models import Photo

log = get_logger(__name__)

MAX_WIDTH = 1600


def _photo_dir() -> Path:
    p = Path(get_settings().PHOTO_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _compress(raw: bytes) -> bytes:
    try:
        from PIL import Image
    except ImportError:
        log.warning("pillow_not_installed_skip_compress")
        return raw
    try:
        img = Image.open(io.BytesIO(raw))
        img = img.convert("RGB") if img.mode not in ("RGB", "L") else img
        if img.width > MAX_WIDTH:
            ratio = MAX_WIDTH / img.width
            new_size = (MAX_WIDTH, int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        return buf.getvalue()
    except Exception as exc:
        log.warning("photo_compress_failed", error=str(exc))
        return raw


def save_photo(
    session: Session,
    content: bytes,
    line_message_id: str,
    assignment_id: int | None,
    tz: ZoneInfo | None = None,
) -> Photo:
    tz = tz or get_settings().tz
    compressed = _compress(content)
    now = datetime.now(tz)
    filename = f"{now.strftime('%Y%m%d')}_{line_message_id}.jpg"
    path = _photo_dir() / filename
    path.write_bytes(compressed)
    relative = str(path.relative_to(_photo_dir().parent)) if path.is_relative_to(_photo_dir().parent) else str(path)

    photo = Photo(
        assignment_id=assignment_id,
        line_message_id=line_message_id,
        file_path=str(path),
    )
    session.add(photo)
    session.commit()
    session.refresh(photo)
    log.info("photo_saved", path=str(path), assignment_id=assignment_id, relative=relative)
    return photo
