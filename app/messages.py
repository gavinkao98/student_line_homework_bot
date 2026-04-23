from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.models import Assignment, Task

_UTC = ZoneInfo("UTC")


def _to_tz(dt: datetime | None, tz: ZoneInfo) -> datetime | None:
    """Ensure datetime is tz-aware (assume UTC if naive), then convert to target tz.

    SQLite doesn't preserve tzinfo, so datetimes read back from DB are naive
    even though we stored aware-UTC. Treat naive as UTC.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_UTC)
    return dt.astimezone(tz)

_WEEKDAY = ["一", "二", "三", "四", "五", "六", "日"]


@dataclass
class TaskStateView:
    task: Task
    completed_at: datetime | None


def _fmt_date(d: date) -> str:
    return f"{d.isoformat()} ({_WEEKDAY[d.weekday()]})"


def _task_row(state: TaskStateView, show_date: bool = False) -> dict:
    is_done = state.completed_at is not None
    label = state.task.text
    if show_date:
        label = f"[{state.task.assignment.assigned_date.strftime('%m-%d')}] {label}"
    row: dict = {
        "type": "box",
        "layout": "horizontal",
        "alignItems": "center",
        "spacing": "sm",
        "contents": [
            {
                "type": "text",
                "text": "✅" if is_done else "☐",
                "flex": 0,
                "size": "lg",
            },
            {
                "type": "text",
                "text": label,
                "flex": 6,
                "wrap": True,
                "size": "md",
                "color": "#888888" if is_done else "#111111",
                "decoration": "line-through" if is_done else "none",
            },
        ],
    }
    if not is_done:
        row["contents"].append(
            {
                "type": "button",
                "style": "primary",
                "color": "#06C755",
                "height": "sm",
                "flex": 3,
                "action": {
                    "type": "postback",
                    "label": "完成",
                    "data": f"action=complete_task&task_id={state.task.id}",
                    "displayText": f"完成：{state.task.text[:15]}",
                },
            }
        )
    return row


def build_assignment_flex(
    assignment: Assignment,
    task_states: list[TaskStateView],
    overdue_task_states: list[TaskStateView] | None = None,
) -> dict:
    total = len(task_states)
    done = sum(1 for s in task_states if s.completed_at is not None)

    body_rows: list[dict] = []
    for s in task_states:
        body_rows.append(_task_row(s))
        body_rows.append({"type": "separator", "margin": "sm"})
    if body_rows and body_rows[-1].get("type") == "separator":
        body_rows.pop()

    summary_text = f"{done} / {total} 完成" if total else "（無子項目）"

    overdue_blocks: list[dict] = []
    if overdue_task_states:
        overdue_blocks.append({"type": "separator", "margin": "lg"})
        overdue_blocks.append(
            {
                "type": "text",
                "text": "📌 之前未完成",
                "weight": "bold",
                "size": "sm",
                "color": "#B22222",
                "margin": "md",
            }
        )
        for s in overdue_task_states:
            overdue_blocks.append(_task_row(s, show_date=True))

    footer_buttons: list[dict] = [
        {
            "type": "button",
            "style": "primary",
            "color": "#06C755",
            "action": {
                "type": "postback",
                "label": "✅ 全部標記完成",
                "data": f"action=complete_all&assignment_id={assignment.id}",
                "displayText": "全部完成",
            },
        },
        {
            "type": "button",
            "style": "secondary",
            "action": {
                "type": "postback",
                "label": "🚩 有不會的觀念",
                "data": "action=stuck_prompt",
                "displayText": "我有不會的",
            },
        },
    ]

    return {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "📚 今日作業", "weight": "bold", "size": "lg"},
                {
                    "type": "text",
                    "text": _fmt_date(assignment.assigned_date),
                    "size": "sm",
                    "color": "#888888",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": body_rows + [
                {"type": "separator", "margin": "md"},
                {
                    "type": "text",
                    "text": summary_text,
                    "size": "sm",
                    "color": "#666666",
                    "margin": "sm",
                    "align": "end",
                },
            ] + overdue_blocks,
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": footer_buttons,
        },
    }


def assignment_alt_text(assignment: Assignment) -> str:
    return f"今日作業：{assignment.content}"


def reminder_text(assignment: Assignment) -> str:
    return (
        "⏰ 提醒：今日作業還沒完成喔\n"
        f"「{assignment.content}」\n"
        "完成後記得點按鈕回報 💪"
    )


def teacher_help_text() -> str:
    return (
        "📖 指令清單\n"
        "/assign <內容> — 今日作業\n"
        "/assign YYYY-MM-DD <內容>\n"
        "/assign 週三: <內容> — 最近一次週三\n"
        "多項目：內容用 ; ；、分開\n"
        "例：/assign 週三: 第2回、第3回\n"
        "\n"
        "批次一整週（每行 週X: 內容）：\n"
        "/assign\n"
        "週一: 第1回\n"
        "週三: 第2回; 生詞\n"
        "週五: 第3回\n"
        "\n"
        "/today /history [N] /pending\n"
        "/schedule [N] — 今天起 N 天排程\n"
        "/students — 目前登記的學生\n"
        "/stuck — 學生標記不會的觀念清單\n"
        "/stuck clear — 標記全部已講解\n"
        "/whoami /help"
    )


def today_status_text(
    assignment: Assignment | None,
    tz: ZoneInfo,
    task_states: list[TaskStateView] | None = None,
    overdue_task_states: list[TaskStateView] | None = None,
    teacher_multi_student_summary: list[tuple[str, int, int]] | None = None,
) -> str:
    """
    task_states: view from one student (or None for teacher-aggregate view)
    teacher_multi_student_summary: [(student_name, done, total), ...] — shown to teacher
    """
    if assignment is None and not overdue_task_states:
        return "今天還沒有登錄作業喔。使用 /assign <內容> 來登錄。"
    lines: list[str] = []
    if assignment is not None:
        lines.append(f"📅 {_fmt_date(assignment.assigned_date)}")
        if task_states:
            for s in task_states:
                mark = "✅" if s.completed_at else "☐"
                lines.append(f"{mark} {s.task.text}")
        elif assignment.tasks:
            for t in assignment.tasks:
                lines.append(f"• {t.text}")
        else:
            lines.append(f"📝 {assignment.content}")
        if teacher_multi_student_summary:
            lines.append("")
            lines.append("各學生進度：")
            for name, done, total in teacher_multi_student_summary:
                icon = "✅" if total > 0 and done == total else "🕒"
                lines.append(f"{icon} {name}：{done}/{total}")
        elif task_states:
            done = sum(1 for s in task_states if s.completed_at is not None)
            total = len(task_states)
            if total:
                lines.append(f"進度：{done}/{total} 完成")
    else:
        lines.append("（今天還沒登錄作業）")

    if overdue_task_states:
        lines.append("")
        lines.append("📌 之前未完成")
        for s in overdue_task_states:
            d = s.task.assignment.assigned_date.strftime("%m-%d")
            lines.append(f"☐ [{d}] {s.task.text}")
    return "\n".join(lines)


def assign_ack_text(assignment: Assignment, was_update: bool, previous_content: str | None) -> str:
    if was_update:
        return (
            f"⚠️ 已覆蓋原本的作業：「{previous_content}」\n"
            f"新作業（{_fmt_date(assignment.assigned_date)}）：{assignment.content}"
        )
    return f"✅ 已登錄 {_fmt_date(assignment.assigned_date)} 作業：{assignment.content}"


def history_text(
    assignments: list[Assignment],
    days: int,
    tz: ZoneInfo,
    progress_map: dict[int, tuple[int, int]] | None = None,
) -> str:
    """
    progress_map: {assignment_id: (any_completed_count, total_tasks)} — aggregated view
    """
    if not assignments:
        return f"📒 最近 {days} 天沒有任何作業紀錄"
    lines = [f"📒 最近 {days} 天"]
    progress_map = progress_map or {}
    for a in assignments:
        done, total = progress_map.get(a.id, (0, len(a.tasks)))
        mark = "✅" if total and done == total else "❌"
        progress_tag = ""
        if total:
            progress_tag = f" ({done}/{total})"
        photo_tag = f"  📸{len(a.photos)}" if a.photos else ""
        date_label = f"{a.assigned_date.strftime('%m-%d')} ({_WEEKDAY[a.assigned_date.weekday()]})"
        lines.append(f"{date_label} {mark}  {a.content}{progress_tag}{photo_tag}")
    return "\n".join(lines)


def pending_text(
    assignments: list[Assignment],
    progress_map: dict[int, tuple[int, int]] | None = None,
) -> str:
    if not assignments:
        return "🎉 目前沒有未完成的作業"
    lines = ["⏳ 未完成作業"]
    progress_map = progress_map or {}
    for a in assignments:
        date_label = f"{a.assigned_date.strftime('%m-%d')} ({_WEEKDAY[a.assigned_date.weekday()]})"
        done, total = progress_map.get(a.id, (0, len(a.tasks)))
        progress_tag = f" ({done}/{total})" if total else ""
        lines.append(f"{date_label}  {a.content}{progress_tag}")
    return "\n".join(lines)


def schedule_text(assignments: list[Assignment], start_date: date, days: int) -> str:
    from datetime import timedelta

    by_date = {a.assigned_date: a for a in assignments}
    end = start_date + timedelta(days=days - 1)
    header = f"📆 近 {days} 天排程 ({start_date.strftime('%m-%d')} ~ {end.strftime('%m-%d')})"
    lines = [header]
    empty_days = 0
    for i in range(days):
        d = start_date + timedelta(days=i)
        date_label = f"{d.strftime('%m-%d')} ({_WEEKDAY[d.weekday()]})"
        a = by_date.get(d)
        if a is None:
            lines.append(f"{date_label} (未派)")
            empty_days += 1
            continue
        total = len(a.tasks)
        icon = "📝"
        lines.append(f"{date_label} {icon} {a.content}" + (f"  ({total} 項)" if total > 1 else ""))
    if empty_days:
        lines.append("")
        lines.append(f"⚠️ 有 {empty_days} 天未派作業")
    return "\n".join(lines)


def complete_ack_text(completed_at: datetime, tz: ZoneInfo) -> str:
    local = _to_tz(completed_at, tz)
    return f"辛苦了！已記錄完成時間 {local.strftime('%H:%M')} 🎉"


def teacher_notify_complete(
    student_label: str, assignment: Assignment, completed_at: datetime, tz: ZoneInfo
) -> str:
    when = _to_tz(completed_at, tz).strftime("%H:%M")
    return f"📮 {student_label} 已完成今日作業「{assignment.content}」（{when}）"


def teacher_notify_task_complete(
    student_label: str, task_text: str, done: int, total: int
) -> str:
    return f"📝 {student_label} 完成了「{task_text}」（{done}/{total}）"


def teacher_notify_photo(student_label: str, assignment: Assignment | None) -> str:
    if assignment is None:
        return f"📸 {student_label} 傳了一張照片（今日尚未派作業）"
    return f"📸 {student_label} 傳了作業照片「{assignment.content}」"


def student_stuck_prompt() -> str:
    return (
        "🚩 今天有什麼觀念或章節不太會？\n"
        "直接打字告訴我就好，例如：\n"
        "「二次函數配方法」\n"
        "「第3回第5題不會」\n\n"
        "如果今天都懂，回覆「無」即可 ✅"
    )


def student_stuck_ack(concept: str, total_open: int) -> str:
    return (
        f"🚩 已登記「{concept}」\n"
        f"目前有 {total_open} 項待解決，下次上課會跟老師討論 📝\n"
        "現在可以開始勾選完成的題目了！"
    )


def student_stuck_ack_none() -> str:
    return (
        "👌 好的，今天沒有不會的地方。\n"
        "現在可以開始勾選完成的題目了！"
    )


def student_stuck_gate_reject() -> str:
    return (
        "請先按底下的 🚩 不會標記，告訴我今天有沒有不會的觀念\n"
        "（如果都懂，按下去後回覆「無」即可）"
    )


def student_stuck_empty_usage() -> str:
    return (
        "請打出你不會的觀念或章節，例如：「二次函數配方法」\n"
        "如果都懂，回「無」即可"
    )


def teacher_stuck_notify(student_label: str, concept: str, total_open_all: int) -> str:
    return (
        f"🚩 {student_label} 標記不會\n"
        f"「{concept}」\n"
        f"（所有學生未解決共 {total_open_all} 項）"
    )


def teacher_stuck_list(grouped: list) -> str:
    """grouped: list[(Student, list[StuckConcept])]"""
    if not grouped:
        return "🎉 目前沒有任何「不會」標記"
    lines = ["🚩 學生未解決的觀念"]
    total = 0
    for student, items in grouped:
        name = student.display_name or "(未命名)"
        lines.append("")
        lines.append(f"👤 {name}（{len(items)} 項）")
        for item in items:
            lines.append(f"・{item.content}")
        total += len(items)
    lines.append("")
    lines.append(f"💡 講解完用 /stuck clear 一鍵清空（目前共 {total} 項）")
    return "\n".join(lines)


def teacher_stuck_cleared(count: int) -> str:
    if count == 0:
        return "目前沒有未解決的項目"
    return f"✅ 已標記 {count} 項為已解決"


def students_list_text(students: list) -> str:
    if not students:
        return (
            "目前沒有登記的學生。\n"
            "請學生加本機器人為好友，他們會自動登記。"
        )
    lines = ["👥 已登記的學生"]
    for i, s in enumerate(students, 1):
        name = s.display_name or "(未命名)"
        lines.append(f"{i}. {name}  {s.line_user_id[:8]}…")
    return "\n".join(lines)
