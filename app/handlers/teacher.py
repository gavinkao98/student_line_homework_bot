from __future__ import annotations

from urllib.parse import parse_qs

from sqlalchemy.orm import Session

from app.config import get_settings
from app.handlers.commands import (
    ParsedCommand,
    parse_batch_assign,
    parse_weekday_token,
    resolve_weekday_to_date,
    split_assign_args,
    try_parse_iso_date,
)
from app.line_client import reply_text
from app.logging import get_logger
from app.messages import (
    assign_ack_text,
    delete_ack_text,
    delete_usage_text,
    history_text,
    pending_text,
    schedule_text,
    students_list_text,
    teacher_help_text,
    teacher_stuck_cleared,
    teacher_stuck_list,
    today_status_text,
)
from app.services import assignment as svc
from app.services import stuck as stuck_svc
from app.services import student as student_svc

log = get_logger(__name__)


_ASSIGN_PROMPT = (
    "📝 派新作業\n"
    "請輸入：/assign <作業內容>\n"
    "例如：/assign 第12回 第3-5頁\n\n"
    "指定日期：/assign 2026-04-25 第13回\n"
    "週幾：/assign 週三: 第2回; 第3回\n"
    "批次：/assign 另起新行，每行 週X: 內容"
)


def handle_teacher_command(session: Session, reply_token: str, cmd: ParsedCommand) -> None:
    name = cmd.name
    if name == "whoami":
        return
    if name == "help":
        reply_text(reply_token, teacher_help_text())
        return
    if name == "assign":
        _handle_assign(session, reply_token, cmd)
        return
    if name == "today":
        _handle_today(session, reply_token)
        return
    if name == "history":
        _handle_history(session, reply_token, cmd)
        return
    if name == "schedule":
        _handle_schedule(session, reply_token, cmd)
        return
    if name == "pending":
        _handle_pending(session, reply_token)
        return
    if name == "students":
        reply_text(reply_token, students_list_text(student_svc.list_active(session)))
        return
    if name == "stuck":
        _handle_stuck(session, reply_token, cmd)
        return
    if name == "delete":
        _handle_delete(session, reply_token, cmd)
        return
    reply_text(reply_token, "未知指令。輸入 /help 查看可用指令。")


def _handle_delete(session: Session, reply_token: str, cmd: ParsedCommand) -> None:
    if not cmd.args or not cmd.args[0].strip():
        reply_text(reply_token, delete_usage_text())
        return
    arg = cmd.args[0].strip()
    today = svc.today_local()
    target_date = None
    if arg.lower() == "today" or arg in ("今日", "今天"):
        target_date = today
    else:
        target_date = try_parse_iso_date(arg)
        if target_date is None:
            weekday = parse_weekday_token(arg)
            if weekday is not None:
                target_date = resolve_weekday_to_date(weekday, today)
    if target_date is None:
        reply_text(reply_token, delete_usage_text())
        return
    deleted = svc.delete_by_date(session, target_date)
    reply_text(reply_token, delete_ack_text(deleted, target_date))


def _handle_stuck(session: Session, reply_token: str, cmd: ParsedCommand) -> None:
    sub = cmd.args[0].strip() if cmd.args and cmd.args[0].strip() else ""
    if sub.lower() == "clear":
        n = stuck_svc.resolve_all(session)
        reply_text(reply_token, teacher_stuck_cleared(n))
        return
    # default: list
    grouped = stuck_svc.list_grouped_by_student(session)
    reply_text(reply_token, teacher_stuck_list(grouped))


def handle_teacher_postback(session: Session, reply_token: str, data: str) -> None:
    params = _parse_postback(data)
    action = params.get("action", "")

    if action == "assign_prompt":
        reply_text(reply_token, _ASSIGN_PROMPT)
        return
    if action == "today":
        _handle_today(session, reply_token)
        return
    if action == "history":
        try:
            days = int(params.get("days", "7"))
        except ValueError:
            days = 7
        days = max(1, min(30, days))
        _do_history(session, reply_token, days)
        return
    if action == "pending":
        _handle_pending(session, reply_token)
        return
    if action == "schedule":
        try:
            days = int(params.get("days", "7"))
        except ValueError:
            days = 7
        days = max(1, min(30, days))
        assigns = svc.list_upcoming(session, days)
        reply_text(reply_token, schedule_text(assigns, svc.today_local(), days))
        return
    if action == "help":
        reply_text(reply_token, teacher_help_text())
        return
    if action == "stats":
        reply_text(reply_token, _stats_text(session))
        return
    log.info("teacher_postback_unknown", action=action, data=data)


def _handle_today(session: Session, reply_token: str) -> None:
    settings = get_settings()
    tz = settings.tz
    a = svc.get_by_date(session, svc.today_local(tz))

    students = student_svc.list_active(session)
    multi_summary = None
    if students and a is not None:
        multi_summary = []
        for s in students:
            done, total = svc.progress_for_student(session, a, s.id)
            multi_summary.append((s.display_name or "學生", done, total))

    # Aggregated overdue from union across students — teacher wants overview
    overdue_views = None
    if settings.CARRY_OVER_UNFINISHED and students:
        seen = set()
        overdue_list = []
        for s in students:
            for ts in svc.list_overdue_task_states(
                session, s.id, settings.CARRY_OVER_WINDOW_DAYS
            ):
                if ts.task.id not in seen:
                    seen.add(ts.task.id)
                    overdue_list.append(ts)
        from app.messages import TaskStateView

        overdue_views = [TaskStateView(task=ts.task, completed_at=None) for ts in overdue_list]

    reply_text(
        reply_token,
        today_status_text(
            a,
            tz,
            task_states=None,
            overdue_task_states=overdue_views,
            teacher_multi_student_summary=multi_summary,
        ),
    )


def _handle_pending(session: Session, reply_token: str) -> None:
    assigns = svc.list_pending(session)
    students = student_svc.list_active(session)
    progress_map: dict[int, tuple[int, int]] = {}
    if students:
        for a in assigns:
            # Show the BEST progress across students (most completed)
            total = len(a.tasks)
            best_done = 0
            for s in students:
                d, _ = svc.progress_for_student(session, a, s.id)
                if d > best_done:
                    best_done = d
            progress_map[a.id] = (best_done, total)
    reply_text(reply_token, pending_text(assigns, progress_map))


def _handle_history(session: Session, reply_token: str, cmd: ParsedCommand) -> None:
    days = 7
    if cmd.args and cmd.args[0].strip():
        arg = cmd.args[0].strip()
        try:
            days = int(arg)
        except ValueError:
            reply_text(reply_token, "用法：/history 或 /history <N>（N ≤ 30）")
            return
        if days < 1 or days > 30:
            reply_text(reply_token, "N 必須在 1 ~ 30 之間。")
            return
    _do_history(session, reply_token, days)


def _do_history(session: Session, reply_token: str, days: int) -> None:
    tz = get_settings().tz
    assigns = svc.list_recent(session, days)
    students = student_svc.list_active(session)
    progress_map: dict[int, tuple[int, int]] = {}
    if students:
        for a in assigns:
            total = len(a.tasks)
            best_done = 0
            for s in students:
                d, _ = svc.progress_for_student(session, a, s.id)
                if d > best_done:
                    best_done = d
            progress_map[a.id] = (best_done, total)
    reply_text(reply_token, history_text(assigns, days, tz, progress_map))


def _handle_schedule(session: Session, reply_token: str, cmd: ParsedCommand) -> None:
    days = 7
    if cmd.args and cmd.args[0].strip():
        try:
            days = int(cmd.args[0].strip())
        except ValueError:
            reply_text(reply_token, "用法：/schedule 或 /schedule <N>（N ≤ 30）")
            return
        if days < 1 or days > 30:
            reply_text(reply_token, "N 必須在 1 ~ 30 之間。")
            return
    assigns = svc.list_upcoming(session, days)
    start = svc.today_local()
    reply_text(reply_token, schedule_text(assigns, start, days))


def _stats_text(session: Session) -> str:
    from datetime import timedelta

    from sqlalchemy import select

    from app.models import Assignment

    today = svc.today_local()
    start = today - timedelta(days=29)
    stmt = (
        select(Assignment)
        .where(Assignment.assigned_date >= start)
        .where(Assignment.assigned_date <= today)
        .order_by(Assignment.assigned_date.desc())
    )
    rows = list(session.execute(stmt).scalars().all())
    students = student_svc.list_active(session)
    total = len(rows)

    if not students:
        return (
            "📊 最近 30 天統計\n"
            f"作業數：{total}\n"
            "（尚無學生登記）"
        )

    # Per-student stats
    lines = ["📊 最近 30 天統計", f"作業數：{total}"]
    for s in students:
        name = s.display_name or "學生"
        done_count = 0
        for a in rows:
            d, t_total = svc.progress_for_student(session, a, s.id)
            if t_total > 0 and d == t_total:
                done_count += 1
        rate = round(done_count / total * 100, 1) if total else 0.0

        # Streak for this student
        today_cursor = today
        streak = 0
        by_date = {a.assigned_date: a for a in rows}
        while today_cursor in by_date:
            a = by_date[today_cursor]
            d, t_total = svc.progress_for_student(session, a, s.id)
            if t_total == 0 or d < t_total:
                break
            streak += 1
            today_cursor = today_cursor - timedelta(days=1)

        lines.append(f"・{name}：完成 {done_count}/{total}（{rate}%），連續 {streak} 天")
    return "\n".join(lines)


def _parse_postback(data: str) -> dict[str, str]:
    parsed = parse_qs(data, keep_blank_values=True)
    return {k: v[0] for k, v in parsed.items() if v}


def _handle_assign(session: Session, reply_token: str, cmd: ParsedCommand) -> None:
    if not cmd.args or not cmd.args[0].strip():
        reply_text(
            reply_token,
            "用法：\n"
            "/assign <內容>\n"
            "/assign YYYY-MM-DD <內容>\n"
            "多項目用 ; 分開；批次多天換行輸入",
        )
        return
    rest = cmd.args[0]
    today = svc.today_local()
    batch = parse_batch_assign(rest, today=today)
    if batch is not None:
        _handle_batch_assign(session, reply_token, batch)
        return
    parsed = split_assign_args(rest, today=today)
    if parsed is None:
        reply_text(reply_token, "作業內容不可為空。")
        return
    target_date, content = parsed
    if target_date is None:
        a, was_update, previous = svc.upsert_today(session, content)
    else:
        a, was_update, previous = svc.upsert_by_date(session, target_date, content)
    reply_text(reply_token, assign_ack_text(a, was_update, previous))


def _handle_batch_assign(session: Session, reply_token: str, batch: list) -> None:
    lines = ["✅ 批次登錄完成"]
    for d, content in batch:
        a, was_update, _prev = svc.upsert_by_date(session, d, content)
        n_tasks = len(a.tasks)
        prefix = "🔁" if was_update else "🆕"
        tag = f"（{n_tasks} 項）" if n_tasks > 1 else ""
        lines.append(f"{prefix} {d.isoformat()}  {content}{tag}")
    reply_text(reply_token, "\n".join(lines))
