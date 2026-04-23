from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.logging import get_logger
from app.models import StuckConcept, Student

log = get_logger(__name__)

AWAITING_WINDOW_MINUTES = 15
NO_STUCK_KEYWORDS = {"無", "沒有", "沒", "none", "无", "N/A", "na", "不會", "沒有不會"}


def _now_utc() -> datetime:
    return datetime.now(ZoneInfo("UTC"))


def record(session: Session, student_id: int, content: str) -> StuckConcept:
    item = StuckConcept(student_id=student_id, content=content.strip())
    session.add(item)
    session.commit()
    session.refresh(item)
    log.info("stuck_recorded", student_id=student_id, content=content)
    return item


def list_open(session: Session, student_id: int | None = None) -> list[StuckConcept]:
    stmt = select(StuckConcept).where(StuckConcept.resolved_at.is_(None))
    if student_id is not None:
        stmt = stmt.where(StuckConcept.student_id == student_id)
    stmt = stmt.order_by(StuckConcept.created_at.asc())
    return list(session.execute(stmt).scalars().all())


def list_grouped_by_student(
    session: Session,
) -> list[tuple[Student, list[StuckConcept]]]:
    items = list_open(session)
    if not items:
        return []
    by_student_id: dict[int, list[StuckConcept]] = {}
    for item in items:
        by_student_id.setdefault(item.student_id, []).append(item)
    result: list[tuple[Student, list[StuckConcept]]] = []
    for sid, items_for_s in by_student_id.items():
        s = session.get(Student, sid)
        if s is None:
            continue
        result.append((s, items_for_s))
    return result


def resolve_all(session: Session, student_id: int | None = None) -> int:
    stmt = select(StuckConcept).where(StuckConcept.resolved_at.is_(None))
    if student_id is not None:
        stmt = stmt.where(StuckConcept.student_id == student_id)
    items = list(session.execute(stmt).scalars().all())
    now = _now_utc()
    for item in items:
        item.resolved_at = now
    if items:
        session.commit()
    return len(items)


def count_open_for_student(session: Session, student_id: int) -> int:
    return len(list_open(session, student_id))


# ---------------- inline flow helpers ----------------


def start_awaiting(session: Session, student_id: int) -> None:
    s = session.get(Student, student_id)
    if s is None:
        return
    s.awaiting_stuck_at = _now_utc()
    session.commit()


def is_awaiting(session: Session, student_id: int) -> bool:
    s = session.get(Student, student_id)
    if s is None or s.awaiting_stuck_at is None:
        return False
    stored = s.awaiting_stuck_at
    if stored.tzinfo is None:
        stored = stored.replace(tzinfo=ZoneInfo("UTC"))
    expires_at = stored + timedelta(minutes=AWAITING_WINDOW_MINUTES)
    return _now_utc() <= expires_at


def clear_awaiting(session: Session, student_id: int) -> None:
    s = session.get(Student, student_id)
    if s is None:
        return
    s.awaiting_stuck_at = None
    session.commit()


def is_no_stuck_response(content: str) -> bool:
    """Whether the text means 'nothing to report'."""
    clean = content.strip().lower().rstrip("。.!?~").strip()
    return clean in {k.lower() for k in NO_STUCK_KEYWORDS}


def submit_inline(
    session: Session, student_id: int, content: str
) -> tuple[StuckConcept | None, bool]:
    """Handle inline-text stuck submission. Returns (stuck_item_or_None, is_no_response).

    If user said "無"/"沒有": no stuck item stored, but gate is cleared.
    Caller should also set AssignmentStudentState.stuck_submitted_at for today's assignment.
    """
    no_response = is_no_stuck_response(content)
    item = None
    if not no_response:
        item = record(session, student_id, content)
    clear_awaiting(session, student_id)
    return item, no_response


def mark_assignment_stuck_submitted(
    session: Session, assignment_id: int, student_id: int
) -> None:
    """Satisfy the stuck-before-complete gate for this (assignment, student)."""
    from app.services.assignment import get_or_create_state

    state = get_or_create_state(session, assignment_id, student_id)
    state.stuck_submitted_at = _now_utc()
    session.commit()


def is_stuck_gate_passed(
    session: Session, assignment_id: int, student_id: int
) -> bool:
    """True if student has submitted a stuck note (or 無) for this assignment."""
    from app.services.assignment import get_state

    state = get_state(session, assignment_id, student_id)
    return state is not None and state.stuck_submitted_at is not None
