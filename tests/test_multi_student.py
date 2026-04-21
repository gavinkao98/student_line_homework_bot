from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import date
from unittest.mock import patch

from app.services import assignment as svc
from app.services import student as student_svc


def _post(client, events):
    body = json.dumps({"events": events}).encode("utf-8")
    sig = base64.b64encode(hmac.new(b"test-secret", body, hashlib.sha256).digest()).decode()
    return client.post("/callback", content=body, headers={"X-Line-Signature": sig})


def test_follow_event_registers_new_student(client, session_factory):
    with patch("app.handlers.webhook.reply_text"):
        _post(client, [{
            "type": "follow",
            "replyToken": "rt1",
            "source": {"userId": "U_new_student_abc", "type": "user"},
        }])
    s = session_factory()
    try:
        st = student_svc.get_by_line_id(s, "U_new_student_abc")
        assert st is not None
        assert st.active
    finally:
        s.close()


def test_unfollow_event_deactivates_student(client, session_factory):
    # Register first
    s = session_factory()
    try:
        student_svc.register_student(s, "U_leaving", "Leaving")
    finally:
        s.close()
    # Then unfollow
    _post(client, [{
        "type": "unfollow",
        "source": {"userId": "U_leaving", "type": "user"},
    }])
    s = session_factory()
    try:
        st = student_svc.get_by_line_id(s, "U_leaving")
        assert st is not None
        assert st.active is False
    finally:
        s.close()


def test_per_student_independent_progress(session, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    s1 = student_svc.register_student(session, "U_s1", "Student1")
    s2 = student_svc.register_student(session, "U_s2", "Student2")
    a, _, _ = svc.upsert_today(session, "A; B")
    t1, _t2 = a.tasks[0].id, a.tasks[1].id

    # s1 completes t1
    svc.mark_task_complete(session, t1, s1.id)
    done1, total1 = svc.progress_for_student(session, a, s1.id)
    done2, total2 = svc.progress_for_student(session, a, s2.id)
    assert done1 == 1 and total1 == 2
    assert done2 == 0 and total2 == 2

    # s2 completes both
    svc.mark_all_tasks_complete(session, a.id, s2.id)
    done1, _ = svc.progress_for_student(session, a, s1.id)
    done2, _ = svc.progress_for_student(session, a, s2.id)
    assert done1 == 1   # unchanged
    assert done2 == 2   # s2 done all

    # s2 state completed_at set, s1 state not
    st1 = svc.get_state(session, a.id, s1.id)
    st2 = svc.get_state(session, a.id, s2.id)
    assert (st1 is None) or (st1.completed_at is None)
    assert st2 is not None and st2.completed_at is not None


def test_cron_push_hits_all_students(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    s = session_factory()
    try:
        student_svc.register_student(s, "U_ms1", "Ms1")
        student_svc.register_student(s, "U_ms2", "Ms2")
        svc.upsert_today(s, "Today")
    finally:
        s.close()
    with patch("app.cron.push_flex") as mp:
        r = client.post(
            "/cron/push-assignment",
            headers={"X-Cron-Token": "test-cron-secret"},
        )
    assert r.status_code == 200
    # Both registered students + the default test student = 3 pushes
    assert mp.call_count >= 3
    pushed_ids = {call.args[0] for call in mp.call_args_list}
    assert "U_ms1" in pushed_ids
    assert "U_ms2" in pushed_ids


def test_cron_reminder_per_student_idempotent(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    s = session_factory()
    try:
        a, _, _ = svc.upsert_today(s, "Remind test")
        st = student_svc.register_student(s, "U_rs", "RS")
        svc.mark_pushed(s, a.id, st.id)
    finally:
        s.close()
    with patch("app.cron.push_text") as mp:
        r = client.post(
            "/cron/send-reminder",
            headers={"X-Cron-Token": "test-cron-secret"},
        )
    assert r.status_code == 200
    # At least 1 reminder sent
    assert mp.call_count >= 1
    # Second call: no more reminders
    with patch("app.cron.push_text") as mp2:
        client.post(
            "/cron/send-reminder",
            headers={"X-Cron-Token": "test-cron-secret"},
        )
    assert mp2.call_count == 0


def test_teacher_students_command(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    s = session_factory()
    try:
        student_svc.register_student(s, "U_alpha", "Alpha")
        student_svc.register_student(s, "U_beta", "Beta")
    finally:
        s.close()
    with patch("app.handlers.teacher.reply_text") as m:
        _post(client, [{
            "type": "message",
            "replyToken": "rt1",
            "source": {"userId": "U_teacher_test", "type": "user"},
            "message": {"type": "text", "id": "m1", "text": "/students"},
        }])
    msg = m.call_args.args[1]
    assert "Alpha" in msg
    assert "Beta" in msg
