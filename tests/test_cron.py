from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from app.services import assignment as svc

HEADERS = {"X-Cron-Token": "test-cron-secret"}


def test_cron_requires_token(client):
    r = client.post("/cron/push-assignment")
    assert r.status_code == 401


def test_cron_wrong_token(client):
    r = client.post("/cron/push-assignment", headers={"X-Cron-Token": "wrong"})
    assert r.status_code == 401


def test_push_no_assignment(client, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    r = client.post("/cron/push-assignment", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["pushed"] is False


def test_push_sends_and_marks(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    s = session_factory()
    try:
        svc.upsert_today(s, "第12回")
    finally:
        s.close()

    with patch("app.cron.push_flex") as mock_push:
        r = client.post("/cron/push-assignment", headers=HEADERS)
        assert r.status_code == 200
        assert r.json()["pushed"] is True
        assert mock_push.called
        assert mock_push.call_args.args[0] == "U_student_test"

    # second call should be no-op
    with patch("app.cron.push_flex") as mock_push2:
        r = client.post("/cron/push-assignment", headers=HEADERS)
        assert r.status_code == 200
        assert r.json()["pushed"] is False
        assert not mock_push2.called


def test_reminder_not_pushed_no_op(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    s = session_factory()
    try:
        svc.upsert_today(s, "第12回")
    finally:
        s.close()
    with patch("app.cron.push_text") as mock_push:
        r = client.post("/cron/send-reminder", headers=HEADERS)
        assert r.status_code == 200
        assert r.json()["reminded"] is False
        assert not mock_push.called


def test_reminder_fires_when_pushed_not_completed(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    s = session_factory()
    try:
        a, _, _ = svc.upsert_today(s, "第12回")
        svc.mark_pushed(s, a.id)
    finally:
        s.close()
    with patch("app.cron.push_text") as mock_push:
        r = client.post("/cron/send-reminder", headers=HEADERS)
        assert r.status_code == 200
        assert r.json()["reminded"] is True
        assert mock_push.called
    # second call: no-op (already reminded)
    with patch("app.cron.push_text") as mock_push2:
        r = client.post("/cron/send-reminder", headers=HEADERS)
        assert r.status_code == 200
        assert r.json()["reminded"] is False
        assert not mock_push2.called


def test_reminder_skipped_when_completed(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    s = session_factory()
    try:
        a, _, _ = svc.upsert_today(s, "第12回")
        svc.mark_pushed(s, a.id)
        svc.mark_complete(s, a.id)
    finally:
        s.close()
    with patch("app.cron.push_text") as mock_push:
        r = client.post("/cron/send-reminder", headers=HEADERS)
        assert r.status_code == 200
        assert r.json()["reminded"] is False
        assert not mock_push.called


def test_admin_stats_streak(client, session_factory, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    s = session_factory()
    try:
        for i in range(3):
            a, _, _ = svc.upsert_by_date(s, date(2026, 4, 21) - timedelta(days=i), f"D-{i}")
            svc.mark_complete(s, a.id)
        # 4 days ago: not completed → breaks streak
        svc.upsert_by_date(s, date(2026, 4, 21) - timedelta(days=3), "D-3")
    finally:
        s.close()
    r = client.get("/cron/admin/stats", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 4
    assert body["completed"] == 3
    assert body["current_streak"] == 3
