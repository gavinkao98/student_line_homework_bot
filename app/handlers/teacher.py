from __future__ import annotations

from urllib.parse import parse_qs

from sqlalchemy.orm import Session

from app.config import get_settings
from app.handlers.commands import ParsedCommand, parse_batch_assign, split_assign_args
from app.line_client import reply_text
from app.logging import get_logger
from app.messages import (
    assign_ack_text,
    history_text,
    pending_text,
    schedule_text,
    teacher_help_text,
    today_status_text,
)
from app.services import assignment as svc

log = get_logger(__name__)


_ASSIGN_PROMPT = (
    "📝 派新作業\n"
    "請輸入：/assign <作業內容>\n"
    "例如：/assign 第12回 第3-5頁\n\n"
    "指定日期：/assign 2026-04-25 第13回"
)


def handle_teacher_command(session: Session, reply_token: str, cmd: ParsedCommand) -> None:
    name = cmd.name
    tz = get_settings().tz
    if name == "whoami":
        # handled upstream
        return
    if name == "help":
        reply_text(reply_token, teacher_help_text())
        return
    if name == "assign":
        _handle_assign(session, reply_token, cmd)
        return
    if name == "today":
        settings = get_settings()
        a = svc.get_by_date(session, svc.today_local(tz))
        overdue = svc.list_overdue_tasks(session, settings.CARRY_OVER_WINDOW_DAYS) if settings.CARRY_OVER_UNFINISHED else []
        reply_text(reply_token, today_status_text(a, tz, overdue_tasks=overdue))
        return
    if name == "history":
        _handle_history(session, reply_token, cmd)
        return
    if name == "schedule":
        _handle_schedule(session, reply_token, cmd)
        return
    if name == "pending":
        assigns = svc.list_pending(session)
        reply_text(reply_token, pending_text(assigns))
        return
    reply_text(reply_token, "未知指令。輸入 /help 查看可用指令。")


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


def handle_teacher_postback(session: Session, reply_token: str, data: str) -> None:
    params = _parse_postback(data)
    action = params.get("action", "")
    tz = get_settings().tz

    if action == "assign_prompt":
        reply_text(reply_token, _ASSIGN_PROMPT)
        return
    if action == "today":
        settings = get_settings()
        a = svc.get_by_date(session, svc.today_local(tz))
        overdue = svc.list_overdue_tasks(session, settings.CARRY_OVER_WINDOW_DAYS) if settings.CARRY_OVER_UNFINISHED else []
        reply_text(reply_token, today_status_text(a, tz, overdue_tasks=overdue))
        return
    if action == "history":
        try:
            days = int(params.get("days", "7"))
        except ValueError:
            days = 7
        days = max(1, min(30, days))
        assigns = svc.list_recent(session, days)
        reply_text(reply_token, history_text(assigns, days, tz))
        return
    if action == "pending":
        assigns = svc.list_pending(session)
        reply_text(reply_token, pending_text(assigns))
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
    total = len(rows)
    completed = sum(1 for r in rows if r.completed_at is not None)
    rate = round(completed / total * 100, 1) if total else 0.0

    by_date = {r.assigned_date: r for r in rows}
    streak = 0
    cursor = today
    while cursor in by_date and by_date[cursor].completed_at is not None:
        streak += 1
        cursor = cursor - timedelta(days=1)

    return (
        "📊 最近 30 天統計\n"
        f"作業數：{total}\n"
        f"完成數：{completed}\n"
        f"完成率：{rate}%\n"
        f"連續完成：{streak} 天"
    )


def _parse_postback(data: str) -> dict[str, str]:
    parsed = parse_qs(data, keep_blank_values=True)
    return {k: v[0] for k, v in parsed.items() if v}


def _handle_history(session: Session, reply_token: str, cmd: ParsedCommand) -> None:
    tz = get_settings().tz
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
    assigns = svc.list_recent(session, days)
    reply_text(reply_token, history_text(assigns, days, tz))


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
