from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.models import Assignment, Task

_WEEKDAY = ["一", "二", "三", "四", "五", "六", "日"]


def _fmt_date(d: date) -> str:
    return f"{d.isoformat()} ({_WEEKDAY[d.weekday()]})"


def _task_row(task: Task, show_date: bool = False) -> dict:
    is_done = task.completed_at is not None
    label_parts = []
    if show_date:
        label_parts.append(f"[{task.assignment.assigned_date.strftime('%m-%d')}]")
    label_parts.append(task.text)
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
                "text": " ".join(label_parts),
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
                    "data": f"action=complete_task&task_id={task.id}",
                    "displayText": f"完成：{task.text[:15]}",
                },
            }
        )
    return row


def build_assignment_flex(
    assignment: Assignment, overdue_tasks: list[Task] | None = None
) -> dict:
    tasks = list(assignment.tasks)
    total = len(tasks)
    done = sum(1 for t in tasks if t.completed_at is not None)

    task_rows: list[dict] = []
    for t in tasks:
        task_rows.append(_task_row(t))
        task_rows.append({"type": "separator", "margin": "sm"})
    if task_rows and task_rows[-1].get("type") == "separator":
        task_rows.pop()

    summary_text = f"{done} / {total} 完成" if total else "（無子項目）"

    overdue_blocks: list[dict] = []
    if overdue_tasks:
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
        for t in overdue_tasks:
            overdue_blocks.append(_task_row(t, show_date=True))

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
                "label": "📸 傳作業照片",
                "data": "action=photo_hint",
                "displayText": "想傳照片",
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
            "contents": task_rows + [
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
        "/whoami /help"
    )


def _task_summary(assignment: Assignment) -> str:
    total = len(assignment.tasks)
    if total == 0:
        return ""
    done = sum(1 for t in assignment.tasks if t.completed_at is not None)
    return f"{done}/{total}"


def today_status_text(
    assignment: Assignment | None,
    tz: ZoneInfo,
    overdue_tasks: list[Task] | None = None,
) -> str:
    if assignment is None and not overdue_tasks:
        return "今天還沒有登錄作業喔。使用 /assign <內容> 來登錄。"
    lines: list[str] = []
    if assignment is not None:
        lines.append(f"📅 {_fmt_date(assignment.assigned_date)}")
        if assignment.tasks:
            for t in assignment.tasks:
                mark = "✅" if t.completed_at else "☐"
                lines.append(f"{mark} {t.text}")
        else:
            lines.append(f"📝 {assignment.content}")
        summary = _task_summary(assignment)
        if summary:
            lines.append(f"進度：{summary} 完成")
        if assignment.completed_at:
            local = assignment.completed_at.astimezone(tz)
            lines.append(f"🎉 全部完成：{local.strftime('%H:%M')}")
        elif assignment.pushed_at:
            lines.append("📤 已推播，等待完成")
        else:
            lines.append("🕒 尚未推播")
        if assignment.photos:
            lines.append(f"📸 照片 {len(assignment.photos)} 張")
    else:
        lines.append("（今天還沒登錄作業）")

    if overdue_tasks:
        lines.append("")
        lines.append("📌 之前未完成")
        for t in overdue_tasks:
            d = t.assignment.assigned_date.strftime("%m-%d")
            lines.append(f"☐ [{d}] {t.text}")
    return "\n".join(lines)


def assign_ack_text(assignment: Assignment, was_update: bool, previous_content: str | None) -> str:
    if was_update:
        return (
            f"⚠️ 已覆蓋原本的作業：「{previous_content}」\n"
            f"新作業（{_fmt_date(assignment.assigned_date)}）：{assignment.content}"
        )
    return f"✅ 已登錄 {_fmt_date(assignment.assigned_date)} 作業：{assignment.content}"


def history_text(assignments: list[Assignment], days: int, tz: ZoneInfo) -> str:
    if not assignments:
        return f"📒 最近 {days} 天沒有任何作業紀錄"
    lines = [f"📒 最近 {days} 天"]
    for a in assignments:
        mark = "✅" if a.completed_at else "❌"
        when = ""
        if a.completed_at:
            when = a.completed_at.astimezone(tz).strftime("%H:%M")
        photo_tag = f"  📸{len(a.photos)}" if a.photos else ""
        date_label = f"{a.assigned_date.strftime('%m-%d')} ({_WEEKDAY[a.assigned_date.weekday()]})"
        progress = _task_summary(a)
        progress_tag = f" ({progress})" if progress and not a.completed_at else ""
        lines.append(f"{date_label} {mark} {when:>5}  {a.content}{progress_tag}{photo_tag}")
    return "\n".join(lines)


def schedule_text(
    assignments: list[Assignment], start_date: date, days: int
) -> str:
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
        icon = "✅" if a.completed_at else "📝"
        total = len(a.tasks)
        done = sum(1 for t in a.tasks if t.completed_at is not None)
        progress = f"  ({done}/{total})" if total else ""
        lines.append(f"{date_label} {icon} {a.content}{progress}")
    if empty_days:
        lines.append("")
        lines.append(f"⚠️ 有 {empty_days} 天未派作業")
    return "\n".join(lines)


def pending_text(assignments: list[Assignment]) -> str:
    if not assignments:
        return "🎉 目前沒有未完成的作業"
    lines = ["⏳ 未完成作業"]
    for a in assignments:
        date_label = f"{a.assigned_date.strftime('%m-%d')} ({_WEEKDAY[a.assigned_date.weekday()]})"
        progress = _task_summary(a)
        progress_tag = f" ({progress})" if progress else ""
        lines.append(f"{date_label}  {a.content}{progress_tag}")
    return "\n".join(lines)


def complete_ack_text(completed_at: datetime, tz: ZoneInfo) -> str:
    local = completed_at.astimezone(tz)
    return f"辛苦了！已記錄完成時間 {local.strftime('%H:%M')} 🎉"


def teacher_notify_complete(assignment: Assignment, tz: ZoneInfo) -> str:
    when = assignment.completed_at.astimezone(tz).strftime("%H:%M") if assignment.completed_at else ""
    return f"📮 學生已完成今日作業「{assignment.content}」（{when}）"


def teacher_notify_photo(assignment: Assignment | None) -> str:
    if assignment is None:
        return "📸 學生傳了一張照片（今日尚未派作業）"
    return f"📸 學生傳了作業照片「{assignment.content}」"
