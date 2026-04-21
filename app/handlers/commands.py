from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

TASK_SEPARATOR_RE = re.compile(r"[;；、\n]+")

_WEEKDAY_TOKEN = r"(?:週|周|星期)?[一二三四五六日天日1-7]|(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)"
BATCH_LINE_RE = re.compile(
    rf"^\s*(\d{{4}}-\d{{2}}-\d{{2}}|{_WEEKDAY_TOKEN})\s*[:：]\s*(.+)\s*$",
    re.IGNORECASE,
)

_WEEKDAY_MAP: dict[str, int] = {
    # Monday = 0 ... Sunday = 6
    "一": 0, "1": 0, "mon": 0,
    "二": 1, "2": 1, "tue": 1,
    "三": 2, "3": 2, "wed": 2,
    "四": 3, "4": 3, "thu": 3,
    "五": 4, "5": 4, "fri": 4,
    "六": 5, "6": 5, "sat": 5,
    "日": 6, "天": 6, "7": 6, "sun": 6,
}


def parse_weekday_token(s: str) -> int | None:
    """Return 0-6 (Mon=0) if s looks like a weekday token, else None."""
    if not s:
        return None
    t = s.strip().lower().removeprefix("週").removeprefix("周").removeprefix("星期")
    return _WEEKDAY_MAP.get(t)


def resolve_weekday_to_date(weekday: int, today: date) -> date:
    """Nearest non-past occurrence of weekday. Today counts if weekday matches."""
    from datetime import timedelta
    delta = (weekday - today.weekday()) % 7
    return today + timedelta(days=delta)


@dataclass
class ParsedCommand:
    name: str
    args: list[str]
    raw: str


_CMD_RE = re.compile(r"^/(\w+)(?:\s+(.*))?$", re.DOTALL)


def parse_command(text: str) -> ParsedCommand | None:
    if not text:
        return None
    text = text.strip()
    m = _CMD_RE.match(text)
    if not m:
        return None
    name = m.group(1).lower()
    rest = (m.group(2) or "").strip()
    args = _split_args(rest) if rest else []
    return ParsedCommand(name=name, args=args, raw=text)


def _split_args(rest: str) -> list[str]:
    return [rest]


def try_parse_iso_date(s: str) -> date | None:
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def split_assign_args(
    rest: str, today: date | None = None
) -> tuple[date | None, str] | None:
    """Parse `<date|weekday>[:] <content>` or just `<content>` (means today).

    Supports a colon between leading token and content (`週三: xxx`), and defaults to
    whitespace delimiter for backwards compat (`2026-04-22 xxx`).
    """
    rest = rest.strip()
    if not rest:
        return None
    # Split on first ":", "：" or whitespace
    m = re.match(r"^(\S+)\s*[:：]\s*(.+)$", rest, re.DOTALL)
    if m is None:
        parts = rest.split(maxsplit=1)
        if len(parts) == 2:
            head, tail = parts[0], parts[1].strip()
        else:
            return None, rest
    else:
        head, tail = m.group(1), m.group(2).strip()

    if not tail:
        return None

    maybe_date = try_parse_iso_date(head)
    if maybe_date is not None:
        return maybe_date, tail

    weekday = parse_weekday_token(head)
    if weekday is not None:
        base = today or date.today()
        return resolve_weekday_to_date(weekday, base), tail

    # Head wasn't a date/weekday — treat whole rest as content for today.
    return None, rest


def split_task_items(content: str) -> list[str]:
    """Split content into task items by ;, ；, 、 or newlines. Empty items dropped."""
    if not content:
        return []
    items = [p.strip() for p in TASK_SEPARATOR_RE.split(content)]
    return [i for i in items if i]


def parse_batch_assign(
    rest: str, today: date | None = None
) -> list[tuple[date, str]] | None:
    """Parse multi-line /assign batch input. Each line: `<YYYY-MM-DD|週X>: <content>`."""
    if "\n" not in rest:
        return None
    base = today or date.today()
    lines = [ln for ln in rest.splitlines() if ln.strip()]
    results: list[tuple[date, str]] = []
    for ln in lines:
        m = BATCH_LINE_RE.match(ln)
        if not m:
            return None
        head, content = m.group(1), m.group(2).strip()
        d = try_parse_iso_date(head)
        if d is None:
            weekday = parse_weekday_token(head)
            if weekday is None:
                return None
            d = resolve_weekday_to_date(weekday, base)
        results.append((d, content))
    return results if results else None
