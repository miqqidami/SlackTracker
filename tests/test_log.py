import pytest

import slacktracker as st
from conftest import iso


def period(start, end, worked, paused=0, note=""):
    return {"start": start, "end": end, "worked": worked, "paused": paused, "note": note}


@pytest.mark.parametrize("seconds, with_seconds, expected", [
    (0, True, "0:00"),
    (65, True, "1:05"),
    (3725, True, "1:02:05"),
    (3725, False, "1:02"),
])
def test_fmt_clock(seconds, with_seconds, expected):
    assert st.fmt_clock(seconds, with_seconds) == expected


@pytest.mark.parametrize("seconds", [0, 42, 605, 3725, 36000 + 59])
def test_duration_round_trips(seconds):
    assert st.parse_duration(st.fmt_duration(seconds)) == seconds


def test_new_log_gets_title_and_day_table(log_file):
    st.record_period(log_file, period(iso(2026, 9, 29, 9), iso(2026, 9, 29, 10, 17, 33), 4653, note="Review"))
    text = log_file.read_text()
    assert text.startswith("# Work Log")
    assert "## 2026-09-29 · Tuesday" in text
    assert "| 09:00:00 | 10:17:33 | 1h 17m 33s | — | Review |" in text
    assert "**Total:** 1h 17m 33s across 1 period" in text


def test_same_day_periods_share_one_table_and_total(log_file):
    st.record_period(log_file, period(iso(2026, 9, 29, 9), iso(2026, 9, 29, 10), 3600))
    st.record_period(log_file, period(iso(2026, 9, 29, 11), iso(2026, 9, 29, 11, 40), 1800, paused=600))
    text = log_file.read_text()
    assert text.count("## 2026-09-29") == 1
    assert text.count(st.TABLE_HEADER) == 1
    assert "| 10m 00s |" in text
    assert "**Total:** 1h 30m 00s across 2 periods" in text
    assert text.count("**Total:**") == 1


def test_new_day_starts_new_section(log_file):
    st.record_period(log_file, period(iso(2026, 9, 29, 9), iso(2026, 9, 29, 10), 3600))
    st.record_period(log_file, period(iso(2026, 9, 30, 9), iso(2026, 9, 30, 9, 30), 1800))
    text = log_file.read_text()
    assert text.index("## 2026-09-29") < text.index("## 2026-09-30")
    assert "**Total:** 30m 00s across 1 period" in text


def test_period_past_midnight_belongs_to_start_day(log_file):
    st.record_period(log_file, period(iso(2026, 9, 29, 23, 30), iso(2026, 9, 30, 0, 45), 4500))
    text = log_file.read_text()
    assert "## 2026-09-29" in text and "## 2026-09-30" not in text
    assert "| 00:45:00 (+1d) |" in text


def test_pipes_in_notes_do_not_break_the_table(log_file):
    st.record_period(log_file, period(iso(2026, 9, 29, 9), iso(2026, 9, 29, 10), 3600, note="API | docs"))
    st.record_period(log_file, period(iso(2026, 9, 29, 11), iso(2026, 9, 29, 12), 3600))
    text = log_file.read_text()
    assert "API \\| docs" in text
    assert "**Total:** 2h 00m 00s across 2 periods" in text


def test_existing_content_and_hand_edits_are_preserved(log_file):
    legacy = "# My notes\n\n## 2026-08-10\n\n- **Time worked:** 10m 32s\n"
    log_file.write_text(legacy)
    st.record_period(log_file, period(iso(2026, 9, 29, 9), iso(2026, 9, 29, 10), 3600, note="first"))
    log_file.write_text(log_file.read_text().replace("| first |", "| edited by hand |"))
    st.record_period(log_file, period(iso(2026, 9, 29, 11), iso(2026, 9, 29, 12), 3600))
    text = log_file.read_text()
    assert text.startswith(legacy.rstrip("\n"))
    assert "| edited by hand |" in text
    assert "**Total:** 2h 00m 00s across 2 periods" in text
