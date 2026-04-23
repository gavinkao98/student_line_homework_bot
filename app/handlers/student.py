from __future__ import annotations

from urllib.parse import parse_qs

from sqlalchemy.orm import Session

from app.config import get_settings
from app.line_client import get_message_content, push_flex, push_text, reply_text
from app.logging import get_logger
from app.messages import (
    TaskStateView,
    assignment_alt_text,
    build_assignment_flex,
    complete_ack_text,
    student_stuck_ack,
    student_stuck_empty_usage,
    student_stuck_prompt,
    teacher_notify_complete,
    teacher_notify_photo,
    teacher_notify_task_complete,
    teacher_stuck_notify,
    today_status_text,
)
from app.models import Student
from app.services import assignment as svc
from app.services import photo as photo_svc
from app.services import stuck as stuck_svc

log = get_logger(__name__)


def _student_label(session: Session, student_id: int) -> str:
    s = session.get(Student, student_id)
    if s is None:
        return "學生"
    return s.display_name or "學生"


def _as_views(states) -> list[TaskStateView]:
    return [TaskStateView(task=s.task, completed_at=s.completed_at) for s in states]


def handle_student_postback(
    session: Session, reply_token: str, data: str, student_id: int
) -> None:
    params = _parse_postback_data(data)
    action = params.get("action")
    if action == "complete":
        _handle_complete_legacy(session, reply_token, params, student_id)
        return
    if action == "complete_task":
        _handle_complete_task(session, reply_token, params, student_id)
        return
    if action == "complete_all":
        _handle_complete_all(session, reply_token, params, student_id)
        return
    if action == "view_today":
        _handle_view_today(session, reply_token, student_id)
        return
    if action == "complete_today":
        _handle_complete_today(session, reply_token, student_id)
        return
    if action == "photo_hint":
        reply_text(reply_token, "📸 請直接在聊天室傳送照片，我會幫你存起來並通知老師。")
        return
    if action == "stuck_prompt":
        reply_text(reply_token, student_stuck_prompt())
        return
    log.info("student_postback_unknown_action", data=data)


def handle_student_text_command(
    session: Session, reply_token: str, text: str, student_id: int
) -> bool:
    """Returns True if handled, False if not recognized (caller may ignore)."""
    from app.handlers.commands import parse_command

    cmd = parse_command(text)
    if cmd is None:
        return False
    if cmd.name == "stuck":
        _handle_stuck_text(session, reply_token, cmd, student_id)
        return True
    return False


def _handle_stuck_text(session: Session, reply_token: str, cmd, student_id: int) -> None:
    content = cmd.args[0].strip() if cmd.args and cmd.args[0].strip() else ""
    if not content:
        reply_text(reply_token, student_stuck_empty_usage())
        return
    stuck_svc.record(session, student_id, content)
    # Confirm to student
    open_count = stuck_svc.count_open_for_student(session, student_id)
    reply_text(reply_token, student_stuck_ack(content, open_count))
    # Notify teacher
    settings = get_settings()
    if settings.TEACHER_USER_ID:
        label = _student_label(session, student_id)
        total_all = len(stuck_svc.list_open(session))
        try:
            push_text(
                settings.TEACHER_USER_ID,
                teacher_stuck_notify(label, content, total_all),
            )
        except Exception as exc:
            log.warning("teacher_stuck_notify_failed", error=str(exc))


def _handle_complete_legacy(
    session: Session, reply_token: str, params: dict[str, str], student_id: int
) -> None:
    raw = params.get("assignment_id")
    if not raw:
        reply_text(reply_token, "資料格式錯誤。")
        return
    try:
        assignment_id = int(raw)
    except ValueError:
        reply_text(reply_token, "資料格式錯誤。")
        return
    _do_complete_all(session, reply_token, assignment_id, student_id)


def _handle_complete_task(
    session: Session, reply_token: str, params: dict[str, str], student_id: int
) -> None:
    tz = get_settings().tz
    raw = params.get("task_id")
    if not raw:
        reply_text(reply_token, "資料格式錯誤。")
        return
    try:
        task_id = int(raw)
    except ValueError:
        reply_text(reply_token, "資料格式錯誤。")
        return
    t, a, newly, assignment_newly = svc.mark_task_complete(session, task_id, student_id)
    if t is None:
        reply_text(reply_token, "找不到對應的項目。")
        return
    if not newly:
        reply_text(reply_token, f"這一項先前已完成囉 ✅\n「{t.text}」")
        return
    done, total = svc.progress_for_student(session, a, student_id) if a else (0, 0)
    if assignment_newly:
        reply_text(reply_token, f"✅ {t.text}\n🎉 全部完成！辛苦了～")
    else:
        reply_text(reply_token, f"✅ {t.text}（{done}/{total}）")
    label = _student_label(session, student_id)
    _notify_teacher(session, a, t, student_id, label, assignment_newly, tz, done, total)


def _handle_complete_all(
    session: Session, reply_token: str, params: dict[str, str], student_id: int
) -> None:
    raw = params.get("assignment_id")
    if not raw:
        reply_text(reply_token, "資料格式錯誤。")
        return
    try:
        assignment_id = int(raw)
    except ValueError:
        reply_text(reply_token, "資料格式錯誤。")
        return
    _do_complete_all(session, reply_token, assignment_id, student_id)


def _do_complete_all(
    session: Session, reply_token: str, assignment_id: int, student_id: int
) -> None:
    tz = get_settings().tz
    a, marked, assignment_newly = svc.mark_all_tasks_complete(session, assignment_id, student_id)
    if a is None:
        reply_text(reply_token, "找不到對應的作業。")
        return
    if marked == 0 and not assignment_newly:
        reply_text(reply_token, "這份作業先前已經全部完成囉 ✅")
        return
    state = svc.get_state(session, assignment_id, student_id)
    completed_at = state.completed_at if state and state.completed_at else svc.now_utc()
    reply_text(reply_token, complete_ack_text(completed_at, tz))
    label = _student_label(session, student_id)
    _notify_teacher(session, a, None, student_id, label, assignment_newly, tz, 0, 0)


def _handle_view_today(session: Session, reply_token: str, student_id: int) -> None:
    settings = get_settings()
    tz = settings.tz
    a = svc.get_by_date(session, svc.today_local(tz))
    overdue_views = _as_views(
        svc.list_overdue_task_states(session, student_id, settings.CARRY_OVER_WINDOW_DAYS)
        if settings.CARRY_OVER_UNFINISHED
        else []
    )
    if a is None and not overdue_views:
        reply_text(reply_token, "今天老師還沒派作業 😊")
        return
    task_views = _as_views(svc.build_task_states(session, a, student_id)) if a else []
    student = session.get(Student, student_id)
    if a is not None and student is not None:
        try:
            push_flex(
                student.line_user_id,
                assignment_alt_text(a),
                build_assignment_flex(a, task_views, overdue_task_states=overdue_views),
            )
        except Exception as exc:
            log.warning("push_flex_view_today_failed", error=str(exc))
    reply_text(
        reply_token,
        today_status_text(a, tz, task_states=task_views, overdue_task_states=overdue_views),
    )


def _handle_complete_today(session: Session, reply_token: str, student_id: int) -> None:
    tz = get_settings().tz
    a = svc.get_by_date(session, svc.today_local(tz))
    if a is None:
        reply_text(reply_token, "今天還沒有作業喔 🙈")
        return
    _do_complete_all(session, reply_token, a.id, student_id)


def handle_student_image(
    session: Session, reply_token: str, message_id: str, student_id: int
) -> None:
    settings = get_settings()
    today_or_latest = svc.latest_open_assignment_for_student(session, student_id)
    try:
        raw = get_message_content(message_id)
    except Exception as exc:
        log.error("download_image_failed", error=str(exc))
        reply_text(reply_token, "照片下載失敗，請稍後重試。")
        return
    photo_svc.save_photo(
        session,
        content=raw,
        line_message_id=message_id,
        assignment_id=today_or_latest.id if today_or_latest else None,
    )
    if today_or_latest is None:
        reply_text(reply_token, "今天還沒有作業喔，照片先幫你存著 📸")
    else:
        reply_text(reply_token, "已收到作業照片 📸")
    label = _student_label(session, student_id)
    if settings.TEACHER_USER_ID:
        try:
            push_text(settings.TEACHER_USER_ID, teacher_notify_photo(label, today_or_latest))
        except Exception as exc:
            log.warning("teacher_notify_photo_failed", error=str(exc))


def _notify_teacher(
    session: Session,
    assignment,
    task,
    student_id: int,
    label: str,
    assignment_newly: bool,
    tz,
    done: int,
    total: int,
) -> None:
    settings = get_settings()
    if not settings.TEACHER_USER_ID or assignment is None:
        return
    try:
        if assignment_newly:
            state = svc.get_state(session, assignment.id, student_id)
            completed_at = state.completed_at if state and state.completed_at else svc.now_utc()
            push_text(
                settings.TEACHER_USER_ID,
                teacher_notify_complete(label, assignment, completed_at, tz),
            )
        elif task is not None:
            push_text(
                settings.TEACHER_USER_ID,
                teacher_notify_task_complete(label, task.text, done, total),
            )
    except Exception as exc:
        log.warning("teacher_notify_failed", error=str(exc))


def _parse_postback_data(data: str) -> dict[str, str]:
    parsed = parse_qs(data, keep_blank_values=True)
    return {k: v[0] for k, v in parsed.items() if v}
