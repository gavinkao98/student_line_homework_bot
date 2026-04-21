from datetime import date

from app.handlers.commands import (
    parse_batch_assign,
    parse_command,
    split_assign_args,
    split_task_items,
)


def test_parse_basic():
    c = parse_command("/help")
    assert c is not None
    assert c.name == "help"
    assert c.args == []


def test_parse_with_content():
    c = parse_command("/assign 第12回 第3-5頁")
    assert c is not None
    assert c.name == "assign"
    assert c.args == ["第12回 第3-5頁"]


def test_parse_non_command():
    assert parse_command("hello") is None
    assert parse_command("") is None
    assert parse_command("   ") is None


def test_parse_case_insensitive_name():
    c = parse_command("/HELP")
    assert c is not None
    assert c.name == "help"


def test_split_assign_today():
    d, content = split_assign_args("第12回")
    assert d is None
    assert content == "第12回"


def test_split_assign_with_date():
    d, content = split_assign_args("2026-05-01 第2回 3-4頁")
    assert d == date(2026, 5, 1)
    assert content == "第2回 3-4頁"


def test_split_assign_invalid_date_is_content():
    d, content = split_assign_args("2026/05/01 foo")
    assert d is None
    assert content == "2026/05/01 foo"


def test_split_assign_empty_returns_none():
    assert split_assign_args("") is None
    assert split_assign_args("   ") is None


def test_split_task_items_semicolon():
    assert split_task_items("A;B ; C") == ["A", "B", "C"]


def test_split_task_items_mixed_separators():
    assert split_task_items("A；B、C\nD") == ["A", "B", "C", "D"]


def test_split_task_items_drops_empties():
    assert split_task_items("A;;B;  ") == ["A", "B"]


def test_split_task_items_single():
    assert split_task_items("第12回") == ["第12回"]


def test_parse_batch_assign_basic():
    text = "\n2026-04-22: 第13回\n2026-04-23: 第14回; 生詞"
    result = parse_batch_assign(text)
    assert result is not None
    assert result == [
        (date(2026, 4, 22), "第13回"),
        (date(2026, 4, 23), "第14回; 生詞"),
    ]


def test_parse_batch_assign_none_for_single_line():
    # No newlines at all → not batch
    assert parse_batch_assign("第12回") is None


def test_parse_batch_assign_rejects_malformed():
    # One valid + one garbage line → reject whole batch
    assert parse_batch_assign("2026-04-22: A\ngarbage") is None


def test_parse_batch_assign_fullwidth_colon():
    # User types a full-width colon (：) → should still work
    assert parse_batch_assign("\n2026-04-22：第13回\n") == [(date(2026, 4, 22), "第13回")]


def test_parse_batch_assign_weekday():
    # today = 2026-04-21 (Tue); 週三 → 2026-04-22, 週五 → 2026-04-24
    text = "\n週三: 第2回\n週五: 第3回; 生詞"
    result = parse_batch_assign(text, today=date(2026, 4, 21))
    assert result == [
        (date(2026, 4, 22), "第2回"),
        (date(2026, 4, 24), "第3回; 生詞"),
    ]


def test_split_assign_weekday_single_line():
    # today = 2026-04-21 (Tue); 週三 → 2026-04-22
    d, content = split_assign_args("週三: 第2回", today=date(2026, 4, 21))
    assert d == date(2026, 4, 22)
    assert content == "第2回"


def test_split_assign_weekday_same_day_is_today():
    # today = 2026-04-22 (Wed); 週三 → 2026-04-22 (today counts)
    d, content = split_assign_args("週三: 第2回", today=date(2026, 4, 22))
    assert d == date(2026, 4, 22)
    assert content == "第2回"


def test_split_assign_weekday_rolls_forward():
    # today = 2026-04-23 (Thu); 週三 → next Wed 2026-04-29
    d, content = split_assign_args("週三: 第2回", today=date(2026, 4, 23))
    assert d == date(2026, 4, 29)


def test_split_assign_weekday_short_form():
    d, content = split_assign_args("三 第2回", today=date(2026, 4, 21))
    assert d == date(2026, 4, 22)
    assert content == "第2回"


def test_saturday_batch_next_week_resolution():
    """User scenario: on Saturday 2026-04-25, 週日 -> 2026-04-26 (tomorrow),
    週一 -> 2026-04-27 (next week), because this week's Monday has passed."""
    saturday = date(2026, 4, 25)
    text = "\n週日: 第一回\n週一: 第二回"
    result = parse_batch_assign(text, today=saturday)
    assert result == [
        (date(2026, 4, 26), "第一回"),
        (date(2026, 4, 27), "第二回"),
    ]


def test_zhou_without_hook_variant():
    """Both 週 and 周 must work."""
    d, _ = split_assign_args("周三: 第2回", today=date(2026, 4, 25))
    # Saturday + 4 days = Wednesday 2026-04-29
    assert d == date(2026, 4, 29)
