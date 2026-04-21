from datetime import date, timedelta

from app.services import assignment as svc


def test_upsert_today_creates(session, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    a, was_update, prev = svc.upsert_today(session, "第12回")
    assert a.id is not None
    assert was_update is False
    assert prev is None
    assert a.content == "第12回"
    assert len(a.tasks) == 1
    assert a.tasks[0].text == "第12回"


def test_upsert_creates_multiple_tasks(session, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    a, _, _ = svc.upsert_today(session, "第12回; 第3-5頁；練習題")
    texts = [t.text for t in a.tasks]
    assert texts == ["第12回", "第3-5頁", "練習題"]


def test_upsert_today_overwrites_and_resets_tasks(session, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    svc.upsert_today(session, "舊作業; 舊子項")
    a, was_update, prev = svc.upsert_today(session, "新作業")
    assert was_update is True
    assert prev == "舊作業; 舊子項"
    assert a.content == "新作業"
    assert [t.text for t in a.tasks] == ["新作業"]
    assert a.pushed_at is None
    assert a.completed_at is None


def test_mark_task_complete_partial(session, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    a, _, _ = svc.upsert_today(session, "A; B; C")
    t1, t2, t3 = a.tasks

    _, ass, newly, assignment_newly = svc.mark_task_complete(session, t1.id)
    assert newly is True
    assert assignment_newly is False
    assert ass.completed_at is None  # not all tasks done yet

    _, ass, newly, assignment_newly = svc.mark_task_complete(session, t1.id)
    assert newly is False  # idempotent

    svc.mark_task_complete(session, t2.id)
    _, ass, newly, assignment_newly = svc.mark_task_complete(session, t3.id)
    assert newly is True
    assert assignment_newly is True
    assert ass.completed_at is not None


def test_mark_all_tasks_complete(session, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    a, _, _ = svc.upsert_today(session, "A; B; C")
    a2, marked, assignment_newly = svc.mark_all_tasks_complete(session, a.id)
    assert marked == 3
    assert assignment_newly is True
    assert a2.completed_at is not None
    assert all(t.completed_at is not None for t in a2.tasks)


def test_mark_all_tasks_complete_idempotent(session, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    a, _, _ = svc.upsert_today(session, "A; B")
    svc.mark_all_tasks_complete(session, a.id)
    _, marked, newly = svc.mark_all_tasks_complete(session, a.id)
    assert marked == 0
    assert newly is False


def test_legacy_mark_complete_still_works(session, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    a, _, _ = svc.upsert_today(session, "X")
    aa, newly1 = svc.mark_complete(session, a.id)
    assert newly1 is True
    assert aa.completed_at is not None
    _, newly2 = svc.mark_complete(session, a.id)
    assert newly2 is False


def test_list_recent(session, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    for i in range(10):
        svc.upsert_by_date(session, date(2026, 4, 21) - timedelta(days=i), f"Day-{i}")
    rows = svc.list_recent(session, 7)
    assert len(rows) == 7
    assert rows[0].assigned_date == date(2026, 4, 21)


def test_list_pending_excludes_completed(session, monkeypatch):
    monkeypatch.setattr(svc, "today_local", lambda tz=None: date(2026, 4, 21))
    a1, _, _ = svc.upsert_by_date(session, date(2026, 4, 20), "A")
    a2, _, _ = svc.upsert_by_date(session, date(2026, 4, 21), "B")
    svc.mark_complete(session, a1.id)
    pending = svc.list_pending(session)
    ids = [p.id for p in pending]
    assert a2.id in ids
    assert a1.id not in ids
