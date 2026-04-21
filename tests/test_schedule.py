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


def _teacher(text: str) -> dict:
    return {
        "type": "message",
        "replyToken": "rt1",
        "source": {"userId": "U_teacher_test", "type": "user"},
        "message": {"type": "text", "id": "m1", "text": text},
    }


def _teacher_postback(data: str) -> dict:
    return {
        "type": "postback",
        "replyToken": "rt1",
        "source": {"userId": "U_teacher_test", "type": "user"},
        "postback": {"data": data},
    }


def test_schedule_shows_seven_days_with_gaps(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    s = session_factory()
    try:
        svc.upsert_by_date(s, date(2026, 4, 21), "今日 A")
        svc.upsert_by_date(s, date(2026, 4, 22), "明日")
        svc.upsert_by_date(s, date(2026, 4, 24), "週五")
        # 4/23, 4/25, 4/26, 4/27 are empty
    finally:
        s.close()

    with patch("app.handlers.teacher.reply_text") as m:
        _post(client, [_teacher("/schedule")])
    msg = m.call_args.args[1]
    assert "📆 近 7 天" in msg
    assert "04-21" in msg and "今日 A" in msg
    assert "04-22" in msg and "明日" in msg
    assert "04-23" in msg and "(未派)" in msg
    assert "04-24" in msg and "週五" in msg
    assert "04-25" in msg and "04-26" in msg and "04-27" in msg
    assert "4 天未派" in msg


def test_schedule_custom_days(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    with patch("app.handlers.teacher.reply_text") as m:
        _post(client, [_teacher("/schedule 3")])
    msg = m.call_args.args[1]
    assert "近 3 天" in msg
    assert msg.count("(未派)") == 3


def test_schedule_rejects_invalid_N(client, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    with patch("app.handlers.teacher.reply_text") as m:
        _post(client, [_teacher("/schedule 99")])
    assert "1 ~ 30" in m.call_args.args[1]


def test_schedule_postback_button(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    s = session_factory()
    try:
        svc.upsert_by_date(s, date(2026, 4, 21), "今天")
    finally:
        s.close()
    with patch("app.handlers.teacher.reply_text") as m:
        _post(client, [_teacher_postback("action=schedule&days=7")])
    assert "📆 近 7 天" in m.call_args.args[1]
