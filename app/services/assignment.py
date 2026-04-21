from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.handlers.commands import split_task_items
from app.models import Assignment, Task


def today_local(tz: ZoneInfo | None = None) -> date:
    tz = tz or get_settings().tz
    return datetime.now(tz).date()


def now_utc() -> datetime:
    return datetime.now(ZoneInfo("UTC"))


def _base_stmt():
    return select(Assignment).options(
        selectinload(Assignment.photos),
        selectinload(Assignment.tasks),
    )


def get_by_date(session: Session, d: date) -> Assignment | None:
    stmt = _base_stmt().where(Assignment.assigned_date == d)
    return session.execute(stmt).scalar_one_or_none()


def get_by_id(session: Session, assignment_id: int) -> Assignment | None:
    stmt = _base_stmt().where(Assignment.id == assignment_id)
    return session.execute(stmt).scalar_one_or_none()


def _rebuild_tasks(session: Session, assignment: Assignment, content: str) -> None:
    """Replace all tasks for an assignment with fresh items parsed from content."""
    for t in list(assignment.tasks):
        session.delete(t)
    session.flush()
    items = split_task_items(content) or [content.strip()]
    for i, text in enumerate(items):
        session.add(Task(assignment_id=assignment.id, position=i, text=text))
    session.flush()


def upsert_by_date(
    session: Session, d: date, content: str
) -> tuple[Assignment, bool, str | None]:
    existing = get_by_date(session, d)
    content = content.strip()
    if existing is None:
        a = Assignment(assigned_date=d, content=content)
        session.add(a)
        session.flush()
        _rebuild_tasks(session, a, content)
        session.commit()
        session.refresh(a)
        return a, False, None
    previous = existing.content
    existing.content = content
    existing.pushed_at = None
    existing.reminded_at = None
    existing.completed_at = None
    _rebuild_tasks(session, existing, content)
    session.commit()
    session.refresh(existing)
    return existing, True, previous


def upsert_today(session: Session, content: str) -> tuple[Assignment, bool, str | None]:
    return upsert_by_date(session, today_local(), content)


def _maybe_complete_assignment(session: Session, assignment: Assignment) -> bool:
    """If all tasks done and assignment not yet completed, mark complete. Returns True if newly completed."""
    tasks = list(assignment.tasks)
    if not tasks:
        return False
    if any(t.completed_at is None for t in tasks):
        return False
    if assignment.completed_at is not None:
        return False
    assignment.completed_at = now_utc()
    session.flush()
    return True


def mark_task_complete(
    session: Session, task_id: int
) -> tuple[Task | None, Assignment | None, bool, bool]:
    """
    Returns (task, assignment, newly_task_completed, assignment_newly_completed).
    Idempotent.
    """
    t = session.get(Task, task_id)
    if t is None:
        return None, None, False, False
    a = get_by_id(session, t.assignment_id)
    if t.completed_at is not None:
        return t, a, False, False
    t.completed_at = now_utc()
    session.flush()
    assignment_newly = False
    if a is not None:
        assignment_newly = _maybe_complete_assignment(session, a)
    session.commit()
    if a is not None:
        session.refresh(a)
    session.refresh(t)
    return t, a, True, assignment_newly


def mark_all_tasks_complete(
    session: Session, assignment_id: int
) -> tuple[Assignment | None, int, bool]:
    """Mark every unfinished task in assignment as complete. Returns (assignment, num_marked, assignment_newly_completed)."""
    a = get_by_id(session, assignment_id)
    if a is None:
        return None, 0, False
    now = now_utc()
    marked = 0
    for t in a.tasks:
        if t.completed_at is None:
            t.completed_at = now
            marked += 1
    session.flush()
    newly = _maybe_complete_assignment(session, a)
    session.commit()
    session.refresh(a)
    return a, marked, newly


def mark_complete(session: Session, assignment_id: int) -> tuple[Assignment | None, bool]:
    """Legacy entry point used by the old single-task complete postback.
    Now equivalent to marking all tasks complete and the assignment complete.
    Returns (assignment, newly_completed_assignment).
    """
    a = get_by_id(session, assignment_id)
    if a is None:
        return None, False
    if a.completed_at is not None:
        return a, False
    _, _, newly = mark_all_tasks_complete(session, assignment_id)
    a = get_by_id(session, assignment_id)
    return a, newly


def mark_pushed(session: Session, assignment_id: int) -> None:
    a = session.get(Assignment, assignment_id)
    if a is None:
        return
    a.pushed_at = now_utc()
    session.commit()


def mark_reminded(session: Session, assignment_id: int) -> None:
    a = session.get(Assignment, assignment_id)
    if a is None:
        return
    a.reminded_at = now_utc()
    session.commit()


def list_recent(session: Session, days: int) -> list[Assignment]:
    start = today_local() - timedelta(days=days - 1)
    end = today_local()
    stmt = (
        select(Assignment)
        .options(selectinload(Assignment.photos))
        .where(and_(Assignment.assigned_date >= start, Assignment.assigned_date <= end))
        .order_by(Assignment.assigned_date.desc())
    )
    return list(session.execute(stmt).scalars().all())


def list_pending(session: Session) -> list[Assignment]:
    stmt = (
        select(Assignment)
        .options(selectinload(Assignment.photos))
        .where(Assignment.completed_at.is_(None))
        .where(Assignment.assigned_date <= today_local())
        .order_by(Assignment.assigned_date.desc())
    )
    return list(session.execute(stmt).scalars().all())


def list_upcoming(session: Session, days: int) -> list[Assignment]:
    """Assignments from today (inclusive) forward for `days` days."""
    start = today_local()
    end = start + timedelta(days=days - 1)
    stmt = (
        _base_stmt()
        .where(Assignment.assigned_date >= start)
        .where(Assignment.assigned_date <= end)
        .order_by(Assignment.assigned_date.asc())
    )
    return list(session.execute(stmt).scalars().all())


def list_overdue_tasks(session: Session, window_days: int = 7) -> list[Task]:
    """Return incomplete tasks from past assignments within the last N days (excluding today)."""
    today = today_local()
    start = today - timedelta(days=window_days)
    stmt = (
        select(Task)
        .join(Assignment, Task.assignment_id == Assignment.id)
        .where(Assignment.assigned_date >= start)
        .where(Assignment.assigned_date < today)
        .where(Task.completed_at.is_(None))
        .order_by(Assignment.assigned_date.asc(), Task.position.asc())
    )
    return list(session.execute(stmt).scalars().all())


def latest_open_assignment(session: Session) -> Assignment | None:
    """Today's assignment if present; else most recent uncompleted past assignment."""
    today_a = get_by_date(session, today_local())
    if today_a is not None:
        return today_a
    stmt = (
        select(Assignment)
        .options(selectinload(Assignment.photos))
        .where(Assignment.completed_at.is_(None))
        .where(Assignment.assigned_date <= today_local())
        .order_by(Assignment.assigned_date.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()
