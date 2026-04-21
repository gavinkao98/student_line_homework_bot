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


def _teacher_text(text: str) -> dict:
    return {
        "type": "message",
        "replyToken": "rt1",
        "source": {"userId": "U_teacher_test", "type": "user"},
        "message": {"type": "text", "id": "m1", "text": text},
    }


def _student_postback(data: str) -> dict:
    return {
        "type": "postback",
        "replyToken": "rt1",
        "source": {"userId": "U_student_test", "type": "user"},
        "postback": {"data": data},
    }


def test_teacher_assign_with_tasks(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    with patch("app.handlers.teacher.reply_text"):
        _post(client, [_teacher_text("/assign 第12回; 第3-5頁; 練習題")])
    s = session_factory()
    try:
        a = svc.get_by_date(s, date(2026, 4, 21))
        assert [t.text for t in a.tasks] == ["第12回", "第3-5頁", "練習題"]
    finally:
        s.close()


def test_teacher_batch_assign(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    batch_text = "/assign\n2026-04-22: 第13回\n2026-04-23: 第14回; 生詞"
    with patch("app.handlers.teacher.reply_text") as m:
        _post(client, [_teacher_text(batch_text)])
    assert "批次登錄" in m.call_args.args[1]
    s = session_factory()
    try:
        a22 = svc.get_by_date(s, date(2026, 4, 22))
        a23 = svc.get_by_date(s, date(2026, 4, 23))
        assert a22 is not None and [t.text for t in a22.tasks] == ["第13回"]
        assert a23 is not None and [t.text for t in a23.tasks] == ["第14回", "生詞"]
    finally:
        s.close()


def test_student_complete_task_partial(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    s = session_factory()
    try:
        a, _, _ = svc.upsert_today(s, "A; B; C")
        t1_id = a.tasks[0].id
    finally:
        s.close()
    with patch("app.handlers.student.reply_text") as m, \
         patch("app.handlers.student.push_text") as mp:
        _post(client, [_student_postback(f"action=complete_task&task_id={t1_id}")])
    msg = m.call_args.args[1]
    assert "1/3" in msg
    # teacher gets progress notification but assignment not yet fully complete
    assert mp.called
    assert "1/3" in mp.call_args.args[1]


def test_student_complete_task_final_triggers_assignment_complete(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    s = session_factory()
    try:
        a, _, _ = svc.upsert_today(s, "A; B")
        t1, t2 = a.tasks[0].id, a.tasks[1].id
        svc.mark_task_complete(s, t1)
    finally:
        s.close()
    with patch("app.handlers.student.reply_text") as m, \
         patch("app.handlers.student.push_text") as mp:
        _post(client, [_student_postback(f"action=complete_task&task_id={t2}")])
    assert "全部完成" in m.call_args.args[1]
    assert mp.called
    # teacher gets "completed today's assignment" style notification
    assert "學生已完成" in mp.call_args.args[1]


def test_student_complete_all(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    s = session_factory()
    try:
        a, _, _ = svc.upsert_today(s, "A; B; C")
        aid = a.id
    finally:
        s.close()
    with patch("app.handlers.student.reply_text") as m, \
         patch("app.handlers.student.push_text") as mp:
        _post(client, [_student_postback(f"action=complete_all&assignment_id={aid}")])
    assert "辛苦了" in m.call_args.args[1]
    assert mp.called
    s = session_factory()
    try:
        a = svc.get_by_date(s, date(2026, 4, 21))
        assert a.completed_at is not None
        assert all(t.completed_at is not None for t in a.tasks)
    finally:
        s.close()
