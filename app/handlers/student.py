from __future__ import annotations

from urllib.parse import parse_qs

from sqlalchemy.orm import Session

from app.config import get_settings
from app.line_client import get_message_content, push_text, reply_text
from app.logging import get_logger
from app.messages import (
    complete_ack_text,
    teacher_notify_complete,
    teacher_notify_photo,
)
from app.services import assignment as svc
from app.services import photo as photo_svc

log = get_logger(__name__)


def handle_student_postback(session: Session, reply_token: str, data: str) -> None:
    params = _parse_postback_data(data)
    action = params.get("action")
    if action == "complete":
        _handle_complete(session, reply_token, params)
        return
    if action == "complete_task":
        _handle_complete_task(session, reply_token, params)
        return
    if action == "complete_all":
        _handle_complete_all(session, reply_token, params)
        return
    if action == "view_today":
        _handle_view_today(session, reply_token)
        return
    if action == "complete_today":
        _handle_complete_today(session, reply_token)
        return
    if action == "photo_hint":
        reply_text(reply_token, "📸 請直接在聊天室傳送照片，我會幫你存起來並通知老師。")
        return
    log.info("student_postback_unknown_action", data=data)


def _handle_complete_task(session: Session, reply_token: str, params: dict[str, str]) -> None:
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
    t, a, newly, assignment_newly = svc.mark_task_complete(session, task_id)
    if t is None:
        reply_text(reply_token, "找不到對應的項目。")
        return
    if not newly:
        reply_text(reply_token, f"這一項先前已完成囉 ✅\n「{t.text}」")
        return
    total = len(a.tasks) if a else 0
    done = sum(1 for x in a.tasks if x.completed_at) if a else 0
    if assignment_newly:
        reply_text(reply_token, f"✅ {t.text}\n🎉 全部完成！辛苦了～")
    else:
        reply_text(reply_token, f"✅ {t.text}（{done}/{total}）")
    _notify_teacher_progress(a, t, assignment_newly, tz)


def _handle_complete_all(session: Session, reply_token: str, params: dict[str, str]) -> None:
    tz = get_settings().tz
    raw = params.get("assignment_id")
    if not raw:
        reply_text(reply_token, "資料格式錯誤。")
        return
    try:
        assignment_id = int(raw)
    except ValueError:
        reply_text(reply_token, "資料格式錯誤。")
        return
    a, marked, assignment_newly = svc.mark_all_tasks_complete(session, assignment_id)
    if a is None:
        reply_text(reply_token, "找不到對應的作業。")
        return
    if marked == 0 and not assignment_newly:
        reply_text(reply_token, "這份作業先前已經全部完成囉 ✅")
        return
    reply_text(reply_token, complete_ack_text(a.completed_at, tz))
    _notify_teacher_progress(a, None, assignment_newly, tz)


def _notify_teacher_progress(a, task, assignment_newly: bool, tz) -> None:
    settings = get_settings()
    if not settings.TEACHER_USER_ID or a is None:
        return
    try:
        if assignment_newly:
            push_text(settings.TEACHER_USER_ID, teacher_notify_complete(a, tz))
        elif task is not None:
            done = sum(1 for x in a.tasks if x.completed_at)
            total = len(a.tasks)
            push_text(
                settings.TEACHER_USER_ID,
                f"📝 學生完成了「{task.text}」（{done}/{total}）",
            )
    except Exception as exc:
        log.warning("teacher_notify_failed", error=str(exc))


def _handle_view_today(session: Session, reply_token: str) -> None:
    from app.line_client import push_flex
    from app.messages import assignment_alt_text, build_assignment_flex, today_status_text

    settings = get_settings()
    tz = settings.tz
    a = svc.get_by_date(session, svc.today_local(tz))
    overdue = (
        svc.list_overdue_tasks(session, settings.CARRY_OVER_WINDOW_DAYS)
        if settings.CARRY_OVER_UNFINISHED
        else []
    )
    if a is None and not overdue:
        reply_text(reply_token, "今天老師還沒派作業 😊")
        return
    if a is not None:
        try:
            if settings.STUDENT_USER_ID:
                push_flex(
                    settings.STUDENT_USER_ID,
                    assignment_alt_text(a),
                    build_assignment_flex(a, overdue_tasks=overdue),
                )
        except Exception as exc:
            log.warning("push_flex_view_today_failed", error=str(exc))
    reply_text(reply_token, today_status_text(a, tz, overdue_tasks=overdue))


def _handle_complete_today(session: Session, reply_token: str) -> None:
    tz = get_settings().tz
    a = svc.get_by_date(session, svc.today_local(tz))
    if a is None:
        reply_text(reply_token, "今天還沒有作業喔 🙈")
        return
    _handle_complete_all(session, reply_token, {"assignment_id": str(a.id)})


def _handle_complete(session: Session, reply_token: str, params: dict[str, str]) -> None:
    raw_id = params.get("assignment_id")
    if not raw_id:
        reply_text(reply_token, "資料格式錯誤。")
        return
    try:
        assignment_id = int(raw_id)
    except ValueError:
        reply_text(reply_token, "資料格式錯誤。")
        return
    _mark_and_notify(session, reply_token, assignment_id)


def _mark_and_notify(session: Session, reply_token: str, assignment_id: int) -> None:
    tz = get_settings().tz
    a, newly = svc.mark_complete(session, assignment_id)
    if a is None:
        reply_text(reply_token, "找不到對應的作業。")
        return
    if not newly:
        reply_text(reply_token, "這份作業先前已經標記完成囉 ✅")
        return
    reply_text(reply_token, complete_ack_text(a.completed_at, tz))
    settings = get_settings()
    if settings.TEACHER_USER_ID:
        try:
            push_text(settings.TEACHER_USER_ID, teacher_notify_complete(a, tz))
        except Exception as exc:
            log.warning("teacher_notify_complete_failed", error=str(exc))


def handle_student_image(session: Session, reply_token: str, message_id: str) -> None:
    settings = get_settings()
    today_or_latest = svc.latest_open_assignment(session)
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
    if settings.TEACHER_USER_ID:
        try:
            push_text(settings.TEACHER_USER_ID, teacher_notify_photo(today_or_latest))
        except Exception as exc:
            log.warning("teacher_notify_photo_failed", error=str(exc))


def _parse_postback_data(data: str) -> dict[str, str]:
    parsed = parse_qs(data, keep_blank_values=True)
    return {k: v[0] for k, v in parsed.items() if v}
