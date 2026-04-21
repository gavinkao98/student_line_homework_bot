from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.line_client import push_flex, push_text
from app.logging import get_logger
from app.messages import (
    TaskStateView,
    assignment_alt_text,
    build_assignment_flex,
    reminder_text,
)
from app.services import assignment as svc
from app.services import student as student_svc

router = APIRouter(prefix="/cron")
log = get_logger(__name__)


def _require_cron_token(
    x_cron_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.CRON_SECRET:
        raise HTTPException(status_code=500, detail="CRON_SECRET not configured")
    if x_cron_token != settings.CRON_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _as_views(states) -> list[TaskStateView]:
    return [TaskStateView(task=s.task, completed_at=s.completed_at) for s in states]


@router.post("/push-assignment", dependencies=[Depends(_require_cron_token)])
def push_assignment(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    student_svc.ensure_seed(session, settings.STUDENT_USER_ID)

    today = svc.today_local(settings.tz)
    a = svc.get_by_date(session, today)
    if a is None:
        log.info("cron_push_no_assignment", date=today.isoformat())
        return {"ok": True, "pushed": False, "reason": "no_assignment"}

    students = student_svc.list_active(session)
    if not students:
        log.warning("cron_push_no_students")
        return {"ok": False, "reason": "no_students"}

    pushed_to: list[str] = []
    skipped: list[dict] = []
    for s in students:
        state = svc.get_state(session, a.id, s.id)
        if state is not None and state.pushed_at is not None:
            skipped.append({"student": s.line_user_id[:8], "reason": "already_pushed"})
            continue
        task_views = _as_views(svc.build_task_states(session, a, s.id))
        overdue_views = (
            _as_views(
                svc.list_overdue_task_states(
                    session, s.id, settings.CARRY_OVER_WINDOW_DAYS
                )
            )
            if settings.CARRY_OVER_UNFINISHED
            else []
        )
        flex = build_assignment_flex(a, task_views, overdue_task_states=overdue_views)
        try:
            push_flex(s.line_user_id, assignment_alt_text(a), flex)
        except Exception as exc:
            log.warning("cron_push_failed_for_student", student_id=s.id, error=str(exc))
            skipped.append({"student": s.line_user_id[:8], "reason": "push_failed"})
            continue
        svc.mark_pushed(session, a.id, s.id)
        pushed_to.append(s.line_user_id[:8])
        log.info("cron_push_sent", assignment_id=a.id, student_id=s.id)

    return {
        "ok": True,
        "pushed": len(pushed_to) > 0,
        "assignment_id": a.id,
        "pushed_to": pushed_to,
        "skipped": skipped,
    }


@router.post("/send-reminder", dependencies=[Depends(_require_cron_token)])
def send_reminder(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    student_svc.ensure_seed(session, settings.STUDENT_USER_ID)

    today = svc.today_local(settings.tz)
    a = svc.get_by_date(session, today)
    if a is None:
        return {"ok": True, "reminded": False, "reason": "no_assignment"}

    students = student_svc.list_active(session)
    if not students:
        return {"ok": False, "reason": "no_students"}

    reminded_to: list[str] = []
    skipped: list[dict] = []
    for s in students:
        state = svc.get_state(session, a.id, s.id)
        if state is None or state.pushed_at is None:
            skipped.append({"student": s.line_user_id[:8], "reason": "not_pushed"})
            continue
        if state.completed_at is not None:
            skipped.append({"student": s.line_user_id[:8], "reason": "already_completed"})
            continue
        if state.reminded_at is not None:
            skipped.append({"student": s.line_user_id[:8], "reason": "already_reminded"})
            continue
        try:
            push_text(s.line_user_id, reminder_text(a))
        except Exception as exc:
            log.warning("cron_reminder_failed_for_student", student_id=s.id, error=str(exc))
            skipped.append({"student": s.line_user_id[:8], "reason": "push_failed"})
            continue
        svc.mark_reminded(session, a.id, s.id)
        reminded_to.append(s.line_user_id[:8])

    return {
        "ok": True,
        "reminded": len(reminded_to) > 0,
        "assignment_id": a.id,
        "reminded_to": reminded_to,
        "skipped": skipped,
    }


@router.post("/admin/setup-rich-menu", dependencies=[Depends(_require_cron_token)])
def setup_rich_menu_endpoint() -> dict:
    from app.services.rich_menu import setup_rich_menus

    return setup_rich_menus()


@router.get("/admin/stats", dependencies=[Depends(_require_cron_token)])
def admin_stats(session: Session = Depends(get_session)) -> dict:
    from datetime import timedelta

    from sqlalchemy import select

    from app.models import Assignment

    today = svc.today_local()
    window_start = today - timedelta(days=29)
    stmt = (
        select(Assignment)
        .where(Assignment.assigned_date >= window_start)
        .where(Assignment.assigned_date <= today)
        .order_by(Assignment.assigned_date.desc())
    )
    rows = list(session.execute(stmt).scalars().all())
    total = len(rows)

    students = student_svc.list_active(session)
    per_student = []
    for st in students:
        done = 0
        for a in rows:
            d, t = svc.progress_for_student(session, a, st.id)
            if t > 0 and d == t:
                done += 1
        rate = round(done / total, 3) if total else 0.0
        # Streak
        streak = 0
        by_date = {a.assigned_date: a for a in rows}
        cursor = today
        while cursor in by_date:
            a = by_date[cursor]
            d, t = svc.progress_for_student(session, a, st.id)
            if t == 0 or d < t:
                break
            streak += 1
            cursor = cursor - timedelta(days=1)
        per_student.append(
            {
                "display_name": st.display_name,
                "line_user_id": st.line_user_id,
                "completed": done,
                "rate": rate,
                "streak": streak,
            }
        )

    return {
        "ok": True,
        "window_days": 30,
        "total": total,
        "students": per_student,
    }
