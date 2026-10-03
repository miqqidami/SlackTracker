# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- A real app in Applications with its own icon, so the timer can be opened from Spotlight, Launchpad and Finder. Opening it while the timer is running shows the Touch Bar controls.
- `APP_NAME=… bash install.sh` names the app, and that name is used in the menu, notifications and Login Items.
- `tools/make_icon.py` renders the app icon.

### Fixed
- Choosing **Quit** no longer makes launchd relaunch the app straight away.

## [2.0.0] — 2026-09-29

A rewrite: SlackTracker is now a manual Start/Stop work timer instead of an automatic Slack-usage tracker.

### Added
- Start, Pause/Resume, Stop and Discard from the menu bar, the Touch Bar, or ⌃⌥⌘S.
- A live timer button pinned in the Touch Bar **Control Strip** (red while recording, amber while paused).
- A full Touch Bar with status, large timer, start time, note and controls. It returns to the Control Strip automatically after an action.
- A menu bar clock with SF Symbols state icons and monospaced digits.
- Per-period notes ("Start with Note…" / "Edit Note…").
- A "Today" submenu listing each logged period, and "Copy Today's Summary" as Markdown.
- The Mac going to sleep pauses the timer and waking resumes it.
- A reminder every 2 hours of running time.
- A Settings submenu, persisted between launches.
- `SIGUSR2` starts or stops the timer from scripts.
- `uninstall.sh`, a test suite and CI.

### Changed
- The log is now a Markdown table per day with a daily total. Existing log content is preserved.
- The timer shows only the current period, never a daily total.
- Notifications are sent with `osascript`, so they work without a signed app bundle.
- Lighter install: `pyobjc-framework-Cocoa` instead of the full PyObjC bundle.

### Fixed
- Touch Bar presentation used a selector that doesn't exist on current macOS, so it silently fell back to activating the app. It now uses `presentSystemModalTouchBar` and no longer steals focus.

### Removed
- Slack process detection, the 06:00 workday rollover and the hourly breakdown.

## [1.0.0] — 2026-05-22

- First public release: automatic tracking of Slack usage per 06:00–06:00 workday, with a Touch Bar timer.

[2.0.0]: https://github.com/miqqidami/SlackTracker/releases/tag/v2.0.0
