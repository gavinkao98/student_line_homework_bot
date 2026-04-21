from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.handlers.commands import split_task_items
from app.models import (
    Assignment,
    AssignmentStudentState,
    Student,
    Task,
    TaskCompletion,
)


def today_local(tz: ZoneInfo | None = None) -> date:
    tz = tz or get_settings().tz
    return datetime.now(tz).date()


def now_utc() -> datetime:
    return datetime.now(ZoneInfo("UTC"))


@dataclass
class TaskState:
    task: Task
    completed_at: datetime | None


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
    # Clear all per-student state since content is replaced
    for state in list(session.execute(
        select(AssignmentStudentState).where(
            AssignmentStudentState.assignment_id == existing.id
        )
    ).scalars().all()):
        session.delete(state)
    _rebuild_tasks(session, existing, content)  # cascades delete task_completions
    session.commit()
    session.refresh(existing)
    return existing, True, previous


def upsert_today(session: Session, content: str) -> tuple[Assignment, bool, str | None]:
    return upsert_by_date(session, today_local(), content)


# ---------------- per-student state helpers ----------------


def get_or_create_state(
    session: Session, assignment_id: int, student_id: int
) -> AssignmentStudentState:
    stmt = select(AssignmentStudentState).where(
        AssignmentStudentState.assignment_id == assignment_id,
        AssignmentStudentState.student_id == student_id,
    )
    state = session.execute(stmt).scalar_one_or_none()
    if state is None:
        state = AssignmentStudentState(
            assignment_id=assignment_id, student_id=student_id
        )
        session.add(state)
        session.flush()
    return state


def get_state(
    session: Session, assignment_id: int, student_id: int
) -> AssignmentStudentState | None:
    stmt = select(AssignmentStudentState).where(
        AssignmentStudentState.assignment_id == assignment_id,
        AssignmentStudentState.student_id == student_id,
    )
    return session.execute(stmt).scalar_one_or_none()


def task_completions_map(
    session: Session, assignment: Assignment, student_id: int
) -> dict[int, datetime]:
    if not assignment.tasks:
        return {}
    task_ids = [t.id for t in assignment.tasks]
    stmt = select(TaskCompletion).where(
        TaskCompletion.task_id.in_(task_ids),
        TaskCompletion.student_id == student_id,
    )
    rows = list(session.execute(stmt).scalars().all())
    return {c.task_id: c.completed_at for c in rows}


def build_task_states(
    session: Session, assignment: Assignment, student_id: int
) -> list[TaskState]:
    cmap = task_completions_map(session, assignment, student_id)
    return [TaskState(task=t, completed_at=cmap.get(t.id)) for t in assignment.tasks]


def progress_for_student(
    session: Session, assignment: Assignment, student_id: int
) -> tuple[int, int]:
    total = len(assignment.tasks)
    if total == 0:
        return 0, 0
    cmap = task_completions_map(session, assignment, student_id)
    return sum(1 for t in assignment.tasks if t.id in cmap), total


def _maybe_complete_assignment(
    session: Session, assignment: Assignment, student_id: int
) -> bool:
    done, total = progress_for_student(session, assignment, student_id)
    if total == 0 or done < total:
        return False
    state = get_or_create_state(session, assignment.id, student_id)
    if state.completed_at is not None:
        return False
    state.completed_at = now_utc()
    # Legacy mirror: first student to complete sets assignment.completed_at
    if assignment.completed_at is None:
        assignment.completed_at = state.completed_at
    session.flush()
    return True


def mark_task_complete(
    session: Session, task_id: int, student_id: int | None = None
) -> tuple[Task | None, Assignment | None, bool, bool]:
    """Returns (task, assignment, newly_completed, assignment_newly_completed)."""
    if student_id is None:
        student_id = _default_student_id(session)
        if student_id is None:
            return None, None, False, False
    t = session.get(Task, task_id)
    if t is None:
        return None, None, False, False
    existing = session.execute(
        select(TaskCompletion).where(
            TaskCompletion.task_id == task_id,
            TaskCompletion.student_id == student_id,
        )
    ).scalar_one_or_none()
    a = get_by_id(session, t.assignment_id)
    if existing is not None:
        return t, a, False, False
    completion = TaskCompletion(
        task_id=task_id, student_id=student_id, completed_at=now_utc()
    )
    session.add(completion)
    # Legacy mirror: first student to complete a task sets task.completed_at
    if t.completed_at is None:
        t.completed_at = completion.completed_at
    session.flush()
    assignment_newly = False
    if a is not None:
        assignment_newly = _maybe_complete_assignment(session, a, student_id)
    session.commit()
    if a is not None:
        session.refresh(a)
    return t, a, True, assignment_newly


def mark_all_tasks_complete(
    session: Session, assignment_id: int, student_id: int | None = None
) -> tuple[Assignment | None, int, bool]:
    if student_id is None:
        student_id = _default_student_id(session)
        if student_id is None:
            return None, 0, False
    a = get_by_id(session, assignment_id)
    if a is None:
        return None, 0, False
    already = task_completions_map(session, a, student_id)
    now = now_utc()
    marked = 0
    for t in a.tasks:
        if t.id in already:
            continue
        session.add(
            TaskCompletion(task_id=t.id, student_id=student_id, completed_at=now)
        )
        # Legacy mirror
        if t.completed_at is None:
            t.completed_at = now
        marked += 1
    session.flush()
    newly = _maybe_complete_assignment(session, a, student_id)
    session.commit()
    session.refresh(a)
    return a, marked, newly


def mark_pushed(session: Session, assignment_id: int, student_id: int | None = None) -> None:
    if student_id is None:
        student_id = _default_student_id(session)
        if student_id is None:
            return
    state = get_or_create_state(session, assignment_id, student_id)
    state.pushed_at = now_utc()
    session.commit()


def mark_reminded(session: Session, assignment_id: int, student_id: int | None = None) -> None:
    if student_id is None:
        student_id = _default_student_id(session)
        if student_id is None:
            return
    state = get_or_create_state(session, assignment_id, student_id)
    state.reminded_at = now_utc()
    session.commit()


# ---------------- queries ----------------


def list_recent(session: Session, days: int) -> list[Assignment]:
    start = today_local() - timedelta(days=days - 1)
    end = today_local()
    stmt = (
        _base_stmt()
        .where(and_(Assignment.assigned_date >= start, Assignment.assigned_date <= end))
        .order_by(Assignment.assigned_date.desc())
    )
    return list(session.execute(stmt).scalars().all())


def list_pending(session: Session) -> list[Assignment]:
    """Assignments where any active student still has unfinished tasks."""
    today = today_local()
    stmt = (
        _base_stmt()
        .where(Assignment.assigned_date <= today)
        .order_by(Assignment.assigned_date.desc())
    )
    all_assigns = list(session.execute(stmt).scalars().all())
    # Filter in Python: assignment is pending if there exists at least one active student
    # for whom not all tasks are done
    active_student_ids = [
        s.id
        for s in session.execute(
            select(Student).where(Student.active.is_(True))
        ).scalars().all()
    ]
    if not active_student_ids:
        # Fallback: if no students, treat assignments as pending if they have any tasks
        return [a for a in all_assigns if a.tasks]
    result: list[Assignment] = []
    for a in all_assigns:
        if not a.tasks:
            continue
        task_ids = [t.id for t in a.tasks]
        # Count completions across active students
        done_count_stmt = select(
            TaskCompletion.student_id, func.count(TaskCompletion.id)
        ).where(
            TaskCompletion.task_id.in_(task_ids),
            TaskCompletion.student_id.in_(active_student_ids),
        ).group_by(TaskCompletion.student_id)
        done_by_student = dict(session.execute(done_count_stmt).all())
        total = len(task_ids)
        if any(done_by_student.get(sid, 0) < total for sid in active_student_ids):
            result.append(a)
    return result


def list_upcoming(session: Session, days: int) -> list[Assignment]:
    start = today_local()
    end = start + timedelta(days=days - 1)
    stmt = (
        _base_stmt()
        .where(Assignment.assigned_date >= start)
        .where(Assignment.assigned_date <= end)
        .order_by(Assignment.assigned_date.asc())
    )
    return list(session.execute(stmt).scalars().all())


def list_overdue_task_states(
    session: Session, student_id: int, window_days: int = 7
) -> list[TaskState]:
    today = today_local()
    start = today - timedelta(days=window_days)
    # Tasks whose assignment is past + in window, with no completion for this student
    stmt = (
        select(Task)
        .join(Assignment, Task.assignment_id == Assignment.id)
        .options(selectinload(Task.assignment))
        .outerjoin(
            TaskCompletion,
            and_(
                TaskCompletion.task_id == Task.id,
                TaskCompletion.student_id == student_id,
            ),
        )
        .where(Assignment.assigned_date >= start)
        .where(Assignment.assigned_date < today)
        .where(TaskCompletion.id.is_(None))
        .order_by(Assignment.assigned_date.asc(), Task.position.asc())
    )
    tasks = list(session.execute(stmt).scalars().all())
    return [TaskState(task=t, completed_at=None) for t in tasks]


def _default_student_id(session: Session) -> int | None:
    """Legacy helper: first active student id (for tests / migration compat)."""
    s = session.execute(
        select(Student).where(Student.active.is_(True)).order_by(Student.added_at).limit(1)
    ).scalar_one_or_none()
    return s.id if s else None


def mark_complete(
    session: Session, assignment_id: int, student_id: int | None = None
) -> tuple[Assignment | None, bool]:
    """Legacy shim: marks all tasks complete for (default or given) student.
    Returns (assignment, newly_completed_assignment)."""
    if student_id is None:
        student_id = _default_student_id(session)
        if student_id is None:
            return None, False
    a, _, newly = mark_all_tasks_complete(session, assignment_id, student_id)
    return a, newly


def list_overdue_tasks(session: Session, window_days: int = 7) -> list[Task]:
    """Legacy shim: overdue tasks from default student's perspective."""
    student_id = _default_student_id(session)
    if student_id is None:
        return []
    states = list_overdue_task_states(session, student_id, window_days)
    return [s.task for s in states]


def latest_open_assignment(session: Session) -> Assignment | None:
    """Legacy shim: use default student."""
    sid = _default_student_id(session)
    if sid is None:
        return get_by_date(session, today_local())
    return latest_open_assignment_for_student(session, sid)


def latest_open_assignment_for_student(
    session: Session, student_id: int
) -> Assignment | None:
    """Today's assignment if exists; else most recent past assignment with unfinished tasks for this student."""
    today_a = get_by_date(session, today_local())
    if today_a is not None:
        return today_a
    # Find most recent past assignment with unfinished tasks for this student
    today = today_local()
    stmt = (
        _base_stmt()
        .where(Assignment.assigned_date <= today)
        .order_by(Assignment.assigned_date.desc())
    )
    past = list(session.execute(stmt).scalars().all())
    for a in past:
        if not a.tasks:
            continue
        done, total = progress_for_student(session, a, student_id)
        if done < total:
            return a
    return None
