# SlackTracker

A tiny macOS menu bar + Touch Bar work timer. Press **Start**, press **Stop**, and the period is written to a Markdown log.

## What it does
- **Start / Stop** from the Touch Bar or from the ⏱ menu in the menu bar at the top of the screen.
- While running, the menu bar shows the elapsed time for the **current period only** (e.g. `⏱ 0:42:10`). Every Start begins again at `0:00:00`.
- **Stop** appends the period (start time, end time, duration) to `~/SlackWorkLog.md`.
- A running period survives quitting/restarting the tracker or a reboot (auto-launches at login via `launchd`).
- **Double-tap Command** presents the Touch Bar controls.

## Install

```bash
bash install.sh
```

You'll see a ⏱ icon appear in your menu bar within a few seconds.

### Permissions
- **Notifications** — allow when prompted (you get one each time a period is logged).
- **Accessibility** — not normally required. SlackTracker registers the global hotkey through macOS Carbon APIs. If Carbon registration fails and it falls back to `pynput`, macOS may ask you to enable the Python binary at `~/.slacktracker/venv/bin/python` in *System Settings → Privacy & Security → Accessibility*.

## Touch Bar

Press `Command` twice quickly anywhere to show:

```
● 0:12:45 | ▶ Start | ■ Stop
```

Only the button that applies is enabled: **Start** when stopped, **Stop** while running. The old `Ctrl + Option + Cmd + T` shortcut still presents the Touch Bar as a fallback.

You can tune the double-tap timing by editing `DOUBLE_COMMAND_SECONDS` at the top of `slacktracker.py`.

## Menu bar

- **Running since … / Timer stopped** — current status
- **▶ Start Timer** / **■ Stop Timer**
- **Show Touch Bar Timer** — same as the hotkey
- **Open log file** — opens `~/SlackWorkLog.md`
- **Quit SlackTracker** — stops the app (a running period is kept and resumes on relaunch)

## Scripting

```bash
pkill -USR2 -f slacktracker.py   # start / stop (toggle)
pkill -USR1 -f slacktracker.py   # present the Touch Bar
```

## Log file

```
## 2026-09-28

- 09:00:00 → 10:17:33 · **1h 17m 33s** (77 min)
- 14:00:00 → 14:25:05 · **25m 05s** (25 min)
```

A new `## <date>` heading is added the first time you log a period on a given day. The in-progress start time is kept in `~/.slacktracker_state.json`.

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.slacktracker.plist
rm -rf ~/.slacktracker ~/Library/LaunchAgents/com.slacktracker.plist
```

## Requirements
- macOS with `python3` (`xcode-select --install` if missing).
- No admin password needed.
