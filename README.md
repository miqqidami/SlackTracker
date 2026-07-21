# SlackTracker

A tiny macOS menu bar app that logs your Slack workday automatically, with a Touch Bar timer for the active 06:00-06:00 workday.

## What it does
- Detects when **Slack.app** opens and starts a timer.
- Keeps tracking in the background (menu bar icon ⏱).
- Pauses the active timer when the laptop sleeps or the lid is closed.
- At **06:00 local time**, finalizes the previous workday, resets the timer, and appends an entry to `~/SlackWorkLog.md`.
- Re-opening Slack in the same 06:00-06:00 workday continues that workday automatically.
- Survives reboots (auto-launches at login via `launchd`).
- **Double-tap Command** presents a styled Touch Bar button with the workday date and live timer.

## Install

```bash
bash install.sh
```

You'll see a ⏱ icon appear in your menu bar within a few seconds.

### Permissions
- **Notifications** — allow when prompted.
- **Accessibility** — not normally required. SlackTracker registers the global hotkey through macOS Carbon APIs. If Carbon registration fails and it falls back to `pynput`, macOS may ask you to enable the Python binary at `~/.slacktracker/venv/bin/python` in *System Settings → Privacy & Security → Accessibility*.

## Touch Bar Shortcut

Press `Command` twice quickly anywhere to show the Touch Bar timer:

```
May 20 | SLACK | 3h 12m 45s
```

It updates every second while SlackTracker is active. The old `Ctrl + Option + Cmd + T` shortcut is still registered as a fallback.

### Touch Bar note
On Touch Bar MacBook Pros, double-tapping `Command` presents a styled Touch Bar button showing the current workday and Slack timer. Tapping that Touch Bar button refreshes/presents the timer again.

You can tune the double-tap timing by editing `DOUBLE_COMMAND_SECONDS` at the top of `slacktracker.py`.

## Log file

SlackTracker keeps one in-progress state file at `~/.slacktracker_state.json`. Closing Slack or putting the laptop to sleep pauses the timer, and reopening Slack or waking the laptop later in the same 06:00-06:00 workday continues from the saved total. The timer resets only when the workday rolls over at 06:00 local time and the previous workday is written to the Markdown log.

```
## 2026-05-20

- **Workday:** 06:00 to 06:00 next day
- **First opened Slack:** 09:12:04
- **Last activity:** 23:59:00
- **Time worked:** 8h 48m 00s (528 min)
- **Sessions:** 3
- **Closed by:** 6am rollover

### Active ranges

- 17:00-20:00: 3h 00m 00s

### Hourly breakdown

- 17:00-18:00: 1h 00m 00s
- 18:00-19:00: 1h 00m 00s
- 19:00-20:00: 1h 00m 00s
```

## Menu options
- **Show Touch Bar Timer** — same as the hotkey
- **Open log file** — opens `~/SlackWorkLog.md`
- **Finish day now** — manually closes today's entry
- **Quit SlackTracker** — stops the app (accumulated time is preserved)

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.slacktracker.plist
rm -rf ~/.slacktracker ~/Library/LaunchAgents/com.slacktracker.plist
```

## Requirements
- macOS with `python3` (`xcode-select --install` if missing).
- No admin password needed.
