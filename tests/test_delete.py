from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import date
from unittest.mock import patch

from app.services import assignment as svc


def _post(client, events):
    body = json.dumps({"events": events}).encode("utf-8")
    sig = base64.b64encode(hmac.new(b"test-secret", body, hashlib.sha256).digest()).decode()
    return client.post("/callback", content=body, headers={"X-Line-Signature": sig})


def _teacher_msg(text: str) -> dict:
    return {
        "type": "message",
        "replyToken": "rt1",
        "source": {"userId": "U_teacher_test", "type": "user"},
        "message": {"type": "text", "id": "m1", "text": text},
    }


def test_delete_today(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    s = session_factory()
    try:
        svc.upsert_today(s, "要刪的作業")
    finally:
        s.close()
    with patch("app.handlers.teacher.reply_text") as m:
        _post(client, [_teacher_msg("/delete today")])
    msg = m.call_args.args[1]
    assert "🗑️" in msg or "已刪除" in msg
    assert "要刪的作業" in msg
    s = session_factory()
    try:
        assert svc.get_by_date(s, date(2026, 4, 21)) is None
    finally:
        s.close()


def test_delete_by_iso_date(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    s = session_factory()
    try:
        svc.upsert_by_date(s, date(2026, 4, 25), "未來要刪")
    finally:
        s.close()
    with patch("app.handlers.teacher.reply_text") as m:
        _post(client, [_teacher_msg("/delete 2026-04-25")])
    assert "已刪除" in m.call_args.args[1]
    s = session_factory()
    try:
        assert svc.get_by_date(s, date(2026, 4, 25)) is None
    finally:
        s.close()


def test_delete_by_weekday(client, session_factory, monkeypatch):
    # today = 2026-04-21 (Tue); 週五 → 2026-04-24
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    s = session_factory()
    try:
        svc.upsert_by_date(s, date(2026, 4, 24), "週五的作業")
    finally:
        s.close()
    with patch("app.handlers.teacher.reply_text") as m:
        _post(client, [_teacher_msg("/delete 週五")])
    assert "已刪除" in m.call_args.args[1]
    s = session_factory()
    try:
        assert svc.get_by_date(s, date(2026, 4, 24)) is None
    finally:
        s.close()


def test_delete_nonexistent_friendly(client, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    with patch("app.handlers.teacher.reply_text") as m:
        _post(client, [_teacher_msg("/delete 2026-04-21")])
    msg = m.call_args.args[1]
    assert "沒有作業" in msg or "無需刪除" in msg


def test_delete_usage_on_empty(client):
    with patch("app.handlers.teacher.reply_text") as m:
        _post(client, [_teacher_msg("/delete")])
    assert "用法" in m.call_args.args[1]
