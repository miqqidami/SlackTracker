import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import slacktracker as st  # noqa: E402


@pytest.fixture
def log_file(tmp_path, monkeypatch):
    path = tmp_path / "WorkLog.md"
    monkeypatch.setattr(st, "LOG_FILE", path)
    return path


@pytest.fixture
def notifications(monkeypatch):
    sent = []
    monkeypatch.setattr(st, "notify", lambda title, message, sound="": sent.append((title, message)))
    return sent


@pytest.fixture
def tracker(log_file, notifications):
    """A SlackTracker with its timer logic intact but no menu bar, Touch Bar or disk state."""
    t = st.SlackTracker.__new__(st.SlackTracker)
    t.current, t.history, t.settings = None, [], dict(st.DEFAULT_SETTINGS)
    t.save_state = lambda: None
    t.refresh_ui = lambda: None
    return t


def iso(*args) -> str:
    return datetime(*args).isoformat()
