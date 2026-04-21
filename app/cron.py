from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.line_client import push_flex, push_text
from app.logging import get_logger
from app.messages import (
    assignment_alt_text,
    build_assignment_flex,
    reminder_text,
)
from app.services import assignment as svc

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


@router.post("/push-assignment", dependencies=[Depends(_require_cron_token)])
def push_assignment(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    today = svc.today_local(settings.tz)
    a = svc.get_by_date(session, today)
    if a is None:
        log.info("cron_push_no_assignment", date=today.isoformat())
        return {"ok": True, "pushed": False, "reason": "no_assignment"}
    if a.pushed_at is not None:
        log.info("cron_push_already_pushed", assignment_id=a.id)
        return {"ok": True, "pushed": False, "reason": "already_pushed"}
    if not settings.STUDENT_USER_ID:
        log.warning("cron_push_no_student_id")
        return {"ok": False, "reason": "no_student_id"}

    overdue = svc.list_overdue_tasks(session, settings.CARRY_OVER_WINDOW_DAYS) if settings.CARRY_OVER_UNFINISHED else []
    flex = build_assignment_flex(a, overdue_tasks=overdue)
    push_flex(settings.STUDENT_USER_ID, assignment_alt_text(a), flex)
    svc.mark_pushed(session, a.id)
    log.info("cron_push_sent", assignment_id=a.id)
    return {"ok": True, "pushed": True, "assignment_id": a.id}


@router.post("/send-reminder", dependencies=[Depends(_require_cron_token)])
def send_reminder(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    today = svc.today_local(settings.tz)
    a = svc.get_by_date(session, today)
    if a is None:
        return {"ok": True, "reminded": False, "reason": "no_assignment"}
    if a.pushed_at is None:
        return {"ok": True, "reminded": False, "reason": "not_pushed"}
    if a.completed_at is not None:
        return {"ok": True, "reminded": False, "reason": "already_completed"}
    if a.reminded_at is not None:
        return {"ok": True, "reminded": False, "reason": "already_reminded"}
    if not settings.STUDENT_USER_ID:
        return {"ok": False, "reason": "no_student_id"}

    push_text(settings.STUDENT_USER_ID, reminder_text(a))
    svc.mark_reminded(session, a.id)
    log.info("cron_reminder_sent", assignment_id=a.id)
    return {"ok": True, "reminded": True, "assignment_id": a.id}


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
    completed = sum(1 for r in rows if r.completed_at is not None)
    rate = (completed / total) if total else 0.0

    streak = 0
    by_date = {r.assigned_date: r for r in rows}
    cursor = today
    while cursor in by_date and by_date[cursor].completed_at is not None:
        streak += 1
        cursor = cursor - timedelta(days=1)

    return {
        "ok": True,
        "window_days": 30,
        "total": total,
        "completed": completed,
        "completion_rate": round(rate, 3),
        "current_streak": streak,
    }
