from __future__ import annotations

import base64
import hashlib
import hmac
import json
from unittest.mock import patch

from app.services import stuck as stuck_svc
from app.services import student as student_svc


def _post(client, events):
    body = json.dumps({"events": events}).encode("utf-8")
    sig = base64.b64encode(hmac.new(b"test-secret", body, hashlib.sha256).digest()).decode()
    return client.post("/callback", content=body, headers={"X-Line-Signature": sig})


def _student_msg(text: str, user_id: str = "U_student_test") -> dict:
    return {
        "type": "message",
        "replyToken": "rt1",
        "source": {"userId": user_id, "type": "user"},
        "message": {"type": "text", "id": "m1", "text": text},
    }


def _teacher_msg(text: str) -> dict:
    return {
        "type": "message",
        "replyToken": "rt1",
        "source": {"userId": "U_teacher_test", "type": "user"},
        "message": {"type": "text", "id": "m1", "text": text},
    }


def test_stuck_record_and_list(session):
    s = student_svc.register_student(session, "U_stuck_test", "StuckTest")
    stuck_svc.record(session, s.id, "二次函數")
    stuck_svc.record(session, s.id, "三角函數")
    items = stuck_svc.list_open(session, s.id)
    assert len(items) == 2
    assert items[0].content == "二次函數"


def test_stuck_resolve_all(session):
    s = student_svc.register_student(session, "U_stuck_r", "StuckR")
    stuck_svc.record(session, s.id, "A")
    stuck_svc.record(session, s.id, "B")
    n = stuck_svc.resolve_all(session, s.id)
    assert n == 2
    assert stuck_svc.list_open(session, s.id) == []


def test_student_stuck_command_records(client, session_factory):
    with patch("app.handlers.student.reply_text") as mr, \
         patch("app.handlers.student.push_text") as mp:
        _post(client, [_student_msg("/stuck 二次函數配方法")])
    # Confirmation to student
    assert mr.called
    assert "二次函數配方法" in mr.call_args.args[1]
    # Teacher gets notified
    assert mp.called
    assert "二次函數配方法" in mp.call_args.args[1]

    # Stored in DB
    s = session_factory()
    try:
        items = stuck_svc.list_open(s)
        assert len(items) == 1
        assert items[0].content == "二次函數配方法"
    finally:
        s.close()


def test_student_stuck_empty_shows_usage(client):
    with patch("app.handlers.student.reply_text") as mr:
        _post(client, [_student_msg("/stuck")])
    assert mr.called
    assert "/stuck" in mr.call_args.args[1]


def test_student_stuck_prompt_postback(client):
    with patch("app.handlers.student.reply_text") as mr:
        _post(client, [{
            "type": "postback",
            "replyToken": "rt1",
            "source": {"userId": "U_student_test", "type": "user"},
            "postback": {"data": "action=stuck_prompt"},
        }])
    assert mr.called
    assert "/stuck" in mr.call_args.args[1]


def test_teacher_stuck_list_and_clear(client, session_factory):
    # Student adds two items
    with patch("app.handlers.student.reply_text"), patch("app.handlers.student.push_text"):
        _post(client, [_student_msg("/stuck 第一個觀念")])
        _post(client, [_student_msg("/stuck 第二個觀念")])

    # Teacher /stuck
    with patch("app.handlers.teacher.reply_text") as m:
        _post(client, [_teacher_msg("/stuck")])
    msg = m.call_args.args[1]
    assert "第一個觀念" in msg
    assert "第二個觀念" in msg

    # Teacher /stuck clear
    with patch("app.handlers.teacher.reply_text") as m:
        _post(client, [_teacher_msg("/stuck clear")])
    assert "2 項" in m.call_args.args[1]

    # After clear, list shows empty
    s = session_factory()
    try:
        assert stuck_svc.list_open(s) == []
    finally:
        s.close()


def test_teacher_stuck_empty_shows_friendly(client):
    with patch("app.handlers.teacher.reply_text") as m:
        _post(client, [_teacher_msg("/stuck")])
    assert "沒有" in m.call_args.args[1]
