from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.logging import get_logger
from app.models import Student

log = get_logger(__name__)


def register_student(
    session: Session, line_user_id: str, display_name: str | None = None
) -> Student:
    """Idempotent: creates new student, or reactivates + updates display name."""
    if not line_user_id:
        raise ValueError("line_user_id cannot be empty")
    s = get_by_line_id(session, line_user_id)
    if s is None:
        s = Student(line_user_id=line_user_id, display_name=display_name, active=True)
        session.add(s)
        session.commit()
        session.refresh(s)
        log.info("student_registered", line_user_id=line_user_id, display_name=display_name)
        return s
    changed = False
    if not s.active:
        s.active = True
        changed = True
    if display_name and s.display_name != display_name:
        s.display_name = display_name
        changed = True
    if changed:
        session.commit()
        session.refresh(s)
        log.info("student_updated", line_user_id=line_user_id, display_name=display_name)
    return s


def deactivate(session: Session, line_user_id: str) -> None:
    s = get_by_line_id(session, line_user_id)
    if s is not None and s.active:
        s.active = False
        session.commit()
        log.info("student_deactivated", line_user_id=line_user_id)


def list_active(session: Session) -> list[Student]:
    stmt = (
        select(Student).where(Student.active.is_(True)).order_by(Student.added_at)
    )
    return list(session.execute(stmt).scalars().all())


def list_all(session: Session) -> list[Student]:
    stmt = select(Student).order_by(Student.added_at)
    return list(session.execute(stmt).scalars().all())


def get_by_line_id(session: Session, line_user_id: str) -> Student | None:
    stmt = select(Student).where(Student.line_user_id == line_user_id)
    return session.execute(stmt).scalar_one_or_none()


def ensure_seed(session: Session, legacy_student_id: str) -> None:
    """Seed: if no students in DB and legacy_student_id is set, register it."""
    if not legacy_student_id:
        return
    any_student = session.execute(select(Student).limit(1)).scalar_one_or_none()
    if any_student is not None:
        return
    register_student(session, legacy_student_id, display_name="（沿用 .env 綁定）")
