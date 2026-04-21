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


def test_list_overdue_tasks(session, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    # Past assignment with partial completion
    a_past, _, _ = svc.upsert_by_date(session, date(2026, 4, 20), "X; Y")
    svc.mark_task_complete(session, a_past.tasks[0].id)  # X done, Y overdue
    # Way-past assignment beyond window (8 days ago)
    svc.upsert_by_date(session, date(2026, 4, 13), "Ancient")
    # Today's assignment (shouldn't appear as overdue)
    svc.upsert_by_date(session, date(2026, 4, 21), "Today")

    overdue = svc.list_overdue_tasks(session, window_days=7)
    texts = [t.text for t in overdue]
    assert "Y" in texts
    assert "X" not in texts     # already completed
    assert "Ancient" not in texts  # outside 7-day window
    assert "Today" not in texts    # today, not overdue


def test_today_postback_includes_overdue(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    s = session_factory()
    try:
        # Yesterday partial
        a_past, _, _ = svc.upsert_by_date(s, date(2026, 4, 20), "未完成任務")
        # Today exists
        svc.upsert_today(s, "今日新作業")
    finally:
        s.close()

    with patch("app.handlers.teacher.reply_text") as m:
        _post(client, [{
            "type": "postback",
            "replyToken": "rt1",
            "source": {"userId": "U_teacher_test", "type": "user"},
            "postback": {"data": "action=today"},
        }])
    msg = m.call_args.args[1]
    assert "今日新作業" in msg
    assert "之前未完成" in msg
    assert "未完成任務" in msg


def test_cron_push_includes_overdue(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    s = session_factory()
    try:
        svc.upsert_by_date(s, date(2026, 4, 20), "昨日任務")
        svc.upsert_today(s, "今日")
    finally:
        s.close()
    with patch("app.cron.push_flex") as mp:
        client.post(
            "/cron/push-assignment",
            headers={"X-Cron-Token": "test-cron-secret"},
        )
    assert mp.called
    # Flex contents are the 3rd positional arg
    flex = mp.call_args.args[2]
    rendered = json.dumps(flex, ensure_ascii=False)
    assert "昨日任務" in rendered
    assert "之前未完成" in rendered
