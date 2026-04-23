from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.logging import get_logger
from app.models import StuckConcept, Student

log = get_logger(__name__)


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
    """Active students + their unresolved stuck concepts, only students with items."""
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
    """Mark all unresolved items as resolved. Returns number marked."""
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
