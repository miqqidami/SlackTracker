from datetime import datetime, timedelta

import slacktracker as st


def ago(**delta) -> str:
    return (datetime.now().replace(microsecond=0) - timedelta(**delta)).isoformat()


def test_start_stop_logs_one_period(tracker, log_file, notifications):
    tracker.start_timer(None, note="Deep work")
    assert tracker.is_running and tracker.note == "Deep work"
    tracker.current["start"] = ago(minutes=25)
    tracker.stop_timer(None)

    assert not tracker.is_active
    logged = tracker.history[-1]
    assert logged["worked"] == 25 * 60 and logged["note"] == "Deep work"
    assert "| 25m 00s | — | Deep work |" in log_file.read_text()
    assert notifications[-1][0] == "Logged 25m 00s"


def test_start_is_ignored_while_active(tracker):
    tracker.start_timer(None)
    first = dict(tracker.current)
    tracker.start_timer(None)
    assert tracker.current == first


def test_paused_time_is_excluded(tracker):
    tracker.current = {"start": ago(hours=1), "paused": 600, "note": "", "paused_at": ago(minutes=5)}
    assert tracker.is_paused
    assert tracker.elapsed() == 45 * 60  # 60 min - 10 min earlier pause - 5 min current pause

    tracker.stop_timer(None)
    logged = tracker.history[-1]
    assert logged["worked"] == 45 * 60
    assert logged["paused"] == 15 * 60


def test_primary_action_cycles_start_pause_resume(tracker):
    tracker.primary_action(None)
    assert tracker.is_running
    tracker.primary_action(None)
    assert tracker.is_paused
    tracker.primary_action(None)
    assert tracker.is_running


def test_sleep_pauses_and_wake_resumes(tracker):
    tracker.start_timer(None)
    tracker.handle_sleep()
    assert tracker.is_paused and tracker.current["auto_paused"]
    tracker.handle_wake()
    assert tracker.is_running


def test_wake_does_not_resume_a_manual_pause(tracker):
    tracker.start_timer(None)
    tracker.pause_timer(None)
    tracker.handle_sleep()
    tracker.handle_wake()
    assert tracker.is_paused


def test_sleep_is_counted_when_setting_is_off(tracker):
    tracker.settings["exclude_sleep"] = False
    tracker.start_timer(None)
    tracker.handle_sleep()
    assert tracker.is_running


def test_discard_logs_nothing(tracker, log_file):
    tracker.start_timer(None)
    tracker.discard_timer(None)
    assert not tracker.is_active
    assert tracker.history == []
    assert not log_file.exists()


def test_reminder_fires_once_per_interval(tracker, notifications):
    tracker.current = {"start": ago(hours=2, minutes=1), "paused": 0, "note": "", "reminded": 0}
    tracker.check_reminder()
    tracker.check_reminder()
    assert [title for title, _ in notifications] == ["Timer running for 2h 01m"]


def test_reminder_can_be_disabled(tracker, notifications):
    tracker.settings["remind_hours"] = 0
    tracker.current = {"start": ago(hours=5), "paused": 0, "note": "", "reminded": 0}
    tracker.check_reminder()
    assert notifications == []


def test_state_from_v1_format_is_migrated(tracker, tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    state.write_text('{"running_since": "2026-09-29T09:00:00"}')
    monkeypatch.setattr(st, "STATE_FILE", state)
    tracker.load_state()
    assert tracker.current["start"] == "2026-09-29T09:00:00"
    assert tracker.current["paused"] == 0
