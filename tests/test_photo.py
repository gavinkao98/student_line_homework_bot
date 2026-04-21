from __future__ import annotations

import io
import shutil
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import get_settings
from app.services import assignment as svc
from app.services import photo as photo_svc


@pytest.fixture(autouse=True)
def _clean_photo_dir():
    p = Path(get_settings().PHOTO_DIR)
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)
    yield
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)


def _png_bytes(width: int = 100, height: int = 100) -> bytes:
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow not installed")
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_save_photo_creates_file(session):
    raw = _png_bytes()
    p = photo_svc.save_photo(session, content=raw, line_message_id="m_abc", assignment_id=None)
    assert p.id is not None
    assert p.assignment_id is None
    assert Path(p.file_path).exists()


def test_student_image_flow(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    s = session_factory()
    try:
        a, _, _ = svc.upsert_today(s, "第12回")
        aid = a.id
    finally:
        s.close()

    import base64
    import hashlib
    import hmac
    import json

    raw = _png_bytes()
    with patch("app.handlers.student.get_message_content", return_value=raw) as mock_dl, \
         patch("app.handlers.student.reply_text") as mock_reply, \
         patch("app.handlers.student.push_text") as mock_push:
        body = json.dumps({"events": [{
            "type": "message",
            "replyToken": "rt1",
            "source": {"userId": "U_student_test", "type": "user"},
            "message": {"type": "image", "id": "m_xyz"},
        }]}).encode("utf-8")
        mac = hmac.new(b"test-secret", body, hashlib.sha256).digest()
        sig = base64.b64encode(mac).decode("utf-8")
        r = client.post("/callback", content=body, headers={"X-Line-Signature": sig})
        assert r.status_code == 200
        assert mock_dl.called
        assert mock_reply.called
        assert "照片" in mock_reply.call_args.args[1]
        assert mock_push.called  # teacher notified

    s = session_factory()
    try:
        from app.models import Photo
        rows = s.query(Photo).all()
        assert len(rows) == 1
        assert rows[0].assignment_id == aid
        assert rows[0].line_message_id == "m_xyz"
    finally:
        s.close()
