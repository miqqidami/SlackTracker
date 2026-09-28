# SlackTracker

A small macOS work timer that lives in your **menu bar** and **Touch Bar**. Press **Start**, press **Stop**, and the period lands in a tidy Markdown log.

## Highlights
- **Period-only timer:** every Start begins at `0:00`. The menu bar and Touch Bar show only the current period, never a daily total.
- **Touch Bar Control Strip button:** the live time is always visible on the right of the Touch Bar (red = recording, amber = paused). Tap it for the full controls.
- **Full Touch Bar controls:** status, big timer, start time and note, then **Start / Pause / Resume**, **Stop** and **Discard** buttons.
- **Menu bar:** the ⏱ icon becomes `◉ 12:45` while running. The menu has the same actions plus notes, today's periods and settings.
- **Markdown log:** Stop adds a row to that day's table in `~/SlackWorkLog.md` and updates the day's total.
- **Notes:** "Start with Note…" / "Edit Note…" attaches a note to the period, and it's saved in the log.
- **Sleep aware:** closing the lid pauses the period and waking resumes it, so sleep time isn't counted.
- **Forgot to stop?** You get a reminder every 2 hours of running time.
- **Safe:** a running period survives quitting, crashes and reboots (auto-launches at login via `launchd`).

## Shortcuts

| Shortcut | Action |
|:--|:--|
| `⌘` `⌘` (double-tap Command) | Show the Touch Bar controls |
| `⌃⌥⌘S` | Start / Stop |
| `⌃⌥⌘T` | Show the Touch Bar controls |

## Touch Bar

```
Control Strip:    … [ 12:45 ] ☀ 🔊 📷
Full controls: ✕  ● REC  12:45   since 09:12 · Code review     [⏸ Pause] [■ Stop] [🗑]
```

After you tap Start, Pause or Stop, the controls return to the Control Strip after 3 seconds. You can turn that off in *Settings*.

## Menu

```
◉ Recording · 12:45
  Started 09:12 · paused 5m · Code review
──────────
⏸ Pause
■ Stop & Log
✎ Edit Note…
🗑 Discard Period
──────────
📅 Today · 2h 10m in 3 periods  ▸  (each period listed)
⧉ Copy Today's Summary
📄 Open Log File
──────────
Show Touch Bar Controls
⚙ Settings  ▸  Pause While Mac Sleeps · Show Seconds in Menu Bar ·
               Auto-hide Touch Bar Controls · Remind Every 2 Hours
──────────
Quit SlackTracker
```

## Log file

```markdown
## 2026-09-29 · Tuesday

| Start | End | Worked | Paused | Note |
|:------|:----|-------:|-------:|:-----|
| 09:00:00 | 10:17:33 | 1h 17m 33s | — | Code review |
| 11:00:00 | 12:10:00 | 1h 00m 00s | 10m 00s | Docs |

**Total:** 2h 17m 33s across 2 periods
```

A period belongs to the day it started. Rows already in the file are kept as they are, so you can edit notes by hand. Anything older in the file is left untouched.

## Install

```bash
bash install.sh
```

### Permissions
- **Notifications:** shown via macOS's built-in `osascript` notifications (listed under *Script Editor* in Notification settings).
- **Accessibility:** not normally required. The shortcuts use macOS Carbon hotkeys. Only if that fails and it falls back to `pynput` will macOS ask you to enable `~/.slacktracker/venv/bin/python` in *System Settings → Privacy & Security → Accessibility*.

## Scripting

```bash
pkill -USR2 -f slacktracker.py   # start / stop
pkill -USR1 -f slacktracker.py   # show the Touch Bar controls
```

State (the running period, recent history, settings) is kept in `~/.slacktracker_state.json`.

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.slacktracker.plist
rm -rf ~/.slacktracker ~/Library/LaunchAgents/com.slacktracker.plist
```

## Requirements
- macOS 11+ with `python3` (`xcode-select --install` if missing). The Control Strip button needs a Touch Bar MacBook Pro.
- No admin password needed.
