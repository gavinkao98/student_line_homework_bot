from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import date
from unittest.mock import patch

from app.services import assignment as svc


def _sign(body: bytes, secret: str = "test-secret") -> str:
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(mac).decode("utf-8")


def _post_events(client, events: list[dict]) -> tuple[int, dict]:
    body = json.dumps({"events": events}).encode("utf-8")
    sig = _sign(body)
    r = client.post("/callback", content=body, headers={"X-Line-Signature": sig})
    return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else {})


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_webhook_bad_signature(client):
    body = json.dumps({"events": []}).encode("utf-8")
    r = client.post("/callback", content=body, headers={"X-Line-Signature": "bogus"})
    assert r.status_code == 400


def test_webhook_good_signature(client):
    status, body = _post_events(client, [])
    assert status == 200
    assert body == {"ok": True}


def test_whoami_teacher(client):
    with patch("app.handlers.webhook.reply_text") as mock_reply, \
         patch("app.handlers.student.reply_text"), \
         patch("app.handlers.teacher.reply_text"):
        status, _ = _post_events(client, [{
            "type": "message",
            "replyToken": "rt1",
            "source": {"userId": "U_teacher_test", "type": "user"},
            "message": {"type": "text", "id": "m1", "text": "/whoami"},
        }])
        assert status == 200
        assert mock_reply.called
        call = mock_reply.call_args
        assert "U_teacher_test" in call.args[1]


def test_teacher_non_command_ignored(client):
    with patch("app.handlers.teacher.reply_text") as mock_reply:
        status, _ = _post_events(client, [{
            "type": "message",
            "replyToken": "rt1",
            "source": {"userId": "U_teacher_test", "type": "user"},
            "message": {"type": "text", "id": "m1", "text": "hello"},
        }])
        assert status == 200
        assert not mock_reply.called


def test_teacher_assign_creates(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    with patch("app.handlers.teacher.reply_text") as mock_reply:
        status, _ = _post_events(client, [{
            "type": "message",
            "replyToken": "rt1",
            "source": {"userId": "U_teacher_test", "type": "user"},
            "message": {"type": "text", "id": "m1", "text": "/assign 第12回"},
        }])
        assert status == 200
        assert mock_reply.called
        msg = mock_reply.call_args.args[1]
        assert "✅" in msg
        assert "第12回" in msg

    # verify DB
    s = session_factory()
    try:
        a = svc.get_by_date(s, date(2026, 4, 21))
        assert a is not None
        assert a.content == "第12回"
    finally:
        s.close()


def test_stranger_gets_rejection(client):
    with patch("app.handlers.webhook.reply_text") as mock_reply:
        status, _ = _post_events(client, [{
            "type": "message",
            "replyToken": "rt1",
            "source": {"userId": "U_stranger", "type": "user"},
            "message": {"type": "text", "id": "m1", "text": "hello"},
        }])
        assert status == 200
        assert mock_reply.called
        assert "私人" in mock_reply.call_args.args[1]


def test_student_postback_complete(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    s = session_factory()
    try:
        a, _, _ = svc.upsert_today(s, "第12回")
        aid = a.id
    finally:
        s.close()

    with patch("app.handlers.student.reply_text") as mock_reply, \
         patch("app.handlers.student.push_text") as mock_push:
        status, _ = _post_events(client, [{
            "type": "postback",
            "replyToken": "rt1",
            "source": {"userId": "U_student_test", "type": "user"},
            "postback": {"data": f"action=complete&assignment_id={aid}"},
        }])
        assert status == 200
        assert mock_reply.called
        assert "辛苦了" in mock_reply.call_args.args[1]
        assert mock_push.called
        assert mock_push.call_args.args[0] == "U_teacher_test"

    s = session_factory()
    try:
        a = svc.get_by_date(s, date(2026, 4, 21))
        assert a.completed_at is not None
    finally:
        s.close()


def test_student_postback_complete_idempotent(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    s = session_factory()
    try:
        a, _, _ = svc.upsert_today(s, "第12回")
        svc.mark_complete(s, a.id)
        aid = a.id
    finally:
        s.close()

    with patch("app.handlers.student.reply_text") as mock_reply, \
         patch("app.handlers.student.push_text") as mock_push:
        status, _ = _post_events(client, [{
            "type": "postback",
            "replyToken": "rt1",
            "source": {"userId": "U_student_test", "type": "user"},
            "postback": {"data": f"action=complete&assignment_id={aid}"},
        }])
        assert status == 200
        # Second complete: should reply "已經標記完成" and NOT notify teacher again
        assert mock_reply.called
        assert "先前" in mock_reply.call_args.args[1] or "已經" in mock_reply.call_args.args[1]
        assert not mock_push.called
