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


def _teacher_postback(data: str) -> dict:
    return {
        "type": "postback",
        "replyToken": "rt1",
        "source": {"userId": "U_teacher_test", "type": "user"},
        "postback": {"data": data},
    }


def _student_postback(data: str) -> dict:
    return {
        "type": "postback",
        "replyToken": "rt1",
        "source": {"userId": "U_student_test", "type": "user"},
        "postback": {"data": data},
    }


def test_teacher_postback_assign_prompt(client):
    with patch("app.handlers.teacher.reply_text") as m:
        _post(client, [_teacher_postback("action=assign_prompt")])
        assert m.called
        assert "/assign" in m.call_args.args[1]


def test_teacher_postback_today(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    s = session_factory()
    try:
        svc.upsert_today(s, "第12回")
    finally:
        s.close()
    with patch("app.handlers.teacher.reply_text") as m:
        _post(client, [_teacher_postback("action=today")])
        assert m.called
        assert "第12回" in m.call_args.args[1]


def test_teacher_postback_history(client, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    with patch("app.handlers.teacher.reply_text") as m:
        _post(client, [_teacher_postback("action=history&days=7")])
        assert m.called
        assert "7 天" in m.call_args.args[1]


def test_teacher_postback_stats(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    s = session_factory()
    try:
        a, _, _ = svc.upsert_today(s, "X")
        svc.mark_complete(s, a.id)
    finally:
        s.close()
    with patch("app.handlers.teacher.reply_text") as m:
        _post(client, [_teacher_postback("action=stats")])
        assert m.called
        msg = m.call_args.args[1]
        # New multi-student format: "・<name>：完成 N/M（X%），連續 K 天"
        assert "完成" in msg
        assert "連續" in msg


def test_student_postback_view_today(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    s = session_factory()
    try:
        svc.upsert_today(s, "第12回")
    finally:
        s.close()
    with patch("app.handlers.student.reply_text") as m:
        _post(client, [_student_postback("action=view_today")])
        assert m.called
        assert "第12回" in m.call_args.args[1]


def test_student_postback_complete_today(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    s = session_factory()
    try:
        svc.upsert_today(s, "第12回")
    finally:
        s.close()
    with patch("app.handlers.student.reply_text") as m, \
         patch("app.handlers.student.push_text") as mp:
        _post(client, [_student_postback("action=complete_today")])
        assert m.called
        assert "辛苦了" in m.call_args.args[1]
        assert mp.called  # teacher notified


def test_student_postback_complete_today_no_assignment(client, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    with patch("app.handlers.student.reply_text") as m:
        _post(client, [_student_postback("action=complete_today")])
        assert m.called
        assert "沒有作業" in m.call_args.args[1]


def test_student_postback_photo_hint(client):
    with patch("app.handlers.student.reply_text") as m:
        _post(client, [_student_postback("action=photo_hint")])
        assert m.called
        assert "照片" in m.call_args.args[1]
