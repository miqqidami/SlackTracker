# Contributing

Thanks for your interest in SlackTracker! Issues and pull requests are welcome.

## Development setup

```bash
git clone https://github.com/miqqidami/SlackTracker.git
cd SlackTracker
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest pyflakes
```

Run the app straight from the checkout (quit the installed copy first from its menu, or run `launchctl unload ~/Library/LaunchAgents/com.slacktracker.plist`):

```bash
python slacktracker.py
```

Logs are printed to the terminal. To try the installed version with your changes, run `bash install.sh` again.

## Before opening a pull request

```bash
pyflakes slacktracker.py tests
pytest
```

CI runs the same checks on macOS with Python 3.10, 3.12 and 3.13.

## Code layout

Everything lives in `slacktracker.py` on purpose, so the app stays easy to read and install:

| Section | What it does |
|:--|:--|
| Formatting / Markdown log | Pure functions: clock formatting and `record_period()`, which maintains the per-day tables |
| `TouchBarController` | Control Strip button and full Touch Bar (PyObjC `NSTouchBar`, private DFRFoundation calls) |
| `SlackTracker` | The `rumps` menu bar app: timer state, menu, shortcuts, sleep handling, reminders |

Keep the timer logic free of UI calls where possible so it stays testable (see `tests/conftest.py` for how tests build a UI-less tracker).

## Guidelines

- Match the surrounding style: small methods, clear names, comments only where the *why* isn't obvious.
- Anything touching private Touch Bar APIs must fail gracefully. SlackTracker has to keep working on Macs without a Touch Bar.
- Never break existing log files: `record_period()` must keep older content and hand edits intact (there's a test for this).
- Add a line to `CHANGELOG.md` under **Unreleased**.
