#!/usr/bin/env python3
"""
SlackTracker — a menu bar + Touch Bar work timer for macOS.

- Start / Pause / Stop from the Touch Bar, the ⏱ menu bar item, or ⌃⌥⌘S.
- A permanent Control Strip button on the Touch Bar shows the live period time;
  tap it (or double-tap ⌘) for the full controls.
- Everything shows only the current period's time. Every Start begins at 0:00:00.
- Stop appends the period to ~/SlackWorkLog.md as a row in that day's table,
  with an updated daily total. Discard throws the period away.
- Optional note per period, sleep time excluded automatically, running period
  survives restarts, reminder every 2 hours so a forgotten timer gets noticed.
"""

import os
import re
import json
import threading
import subprocess
import ctypes
import signal
from datetime import datetime, date
from pathlib import Path
from time import monotonic

import rumps

# --- AppKit / pynput are optional but recommended ---
try:
    from AppKit import (
        NSPanel, NSColor, NSFont, NSScreen, NSApp, NSImage, NSBundle,
        NSBackingStoreBuffered,
        NSFloatingWindowLevel, NSMakeRect, NSWorkspace,
        NSWorkspaceWillSleepNotification, NSWorkspaceDidWakeNotification,
        NSWindowStyleMaskBorderless,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorFullScreenAuxiliary,
        NSApplicationActivationPolicyAccessory,
        NSApplicationActivateIgnoringOtherApps, NSRunningApplication,
        NSEvent, NSEventMaskFlagsChanged, NSEventModifierFlagCommand,
        NSAttributedString, NSFontAttributeName, NSForegroundColorAttributeName,
        NSPasteboard, NSPasteboardTypeString,
    )
    from Foundation import NSObject
    import objc
    HAVE_APPKIT = True
except Exception:
    HAVE_APPKIT = False
    NSObject = object

try:
    from AppKit import (
        NSTouchBar, NSTouchBarItem, NSCustomTouchBarItem, NSButton, NSTextField,
        NSButtonTypeMomentaryPushIn, NSBezelStyleRounded,
        NSTouchBarItemIdentifierFlexibleSpace, NSTouchBarItemIdentifierFixedSpaceSmall,
    )
    HAVE_TOUCHBAR = True
except Exception:
    HAVE_TOUCHBAR = False

try:
    from pynput import keyboard as pkeyboard
    HAVE_PYNPUT = True
except Exception:
    HAVE_PYNPUT = False


__version__ = "2.0.0"
REPO_URL = "https://github.com/miqqidami/SlackTracker"

HOME = Path.home()
LOG_FILE = HOME / "SlackWorkLog.md"
STATE_FILE = HOME / ".slacktracker_state.json"
HISTORY_LIMIT = 200
DOUBLE_COMMAND_SECONDS = 0.45
TOUCHBAR_AUTO_HIDE_SECONDS = 3

# Global shortcuts (Carbon). Modifiers: cmdKey | optionKey | controlKey.
CARBON_MODIFIERS = 0x0100 | 0x0800 | 0x1000
HOTKEY_SHOW = (1, 17, "Ctrl+Option+Cmd+T")    # id, ANSI T, label
HOTKEY_TOGGLE = (2, 1, "Ctrl+Option+Cmd+S")   # id, ANSI S, label
PYNPUT_HOTKEYS = {"show": "<ctrl>+<alt>+<cmd>+t", "toggle": "<ctrl>+<alt>+<cmd>+s"}

DEFAULT_SETTINGS = {
    "exclude_sleep": True,       # sleeping Mac pauses the period automatically
    "menu_seconds": True,        # show seconds in the menu bar clock
    "touchbar_auto_hide": True,  # return to the Control Strip after Start/Stop
    "remind_hours": 2,           # notify every N running hours (0 = off)
}

GREEN = (0.19, 0.69, 0.38)
AMBER = (0.93, 0.62, 0.14)
RED = (0.86, 0.26, 0.24)
GREY = (0.36, 0.36, 0.40)
MUTED = (0.62, 0.62, 0.66)
WHITE = (1.0, 1.0, 1.0)

TABLE_HEADER = "| Start | End | Worked | Paused | Note |"
TABLE_RULE = "|:------|:----|-------:|-------:|:-----|"


# -------------------- formatting --------------------

def fmt_clock(seconds: int, with_seconds: bool = True) -> str:
    """Compact clock: 12:05 / 1:02:05 (or 0:12 / 1:02 without seconds)."""
    h, rem = divmod(max(0, int(seconds)), 3600)
    m, s = divmod(rem, 60)
    if not with_seconds:
        return f"{h}:{m:02d}"
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_duration(seconds: int) -> str:
    h, rem = divmod(max(0, int(seconds)), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def fmt_short(seconds: int) -> str:
    h, rem = divmod(max(0, int(seconds)), 3600)
    m = rem // 60
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m" if m else f"{int(seconds)}s"


def parse_duration(text: str) -> int:
    total = 0
    for value, unit in re.findall(r"(\d+)\s*([hms])", text):
        total += int(value) * {"h": 3600, "m": 60, "s": 1}[unit]
    return total


def ellipsize(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def log_debug(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def notify(title: str, message: str, sound: str = "") -> None:
    """Post a macOS notification without blocking the UI thread."""
    def esc(value):
        return value.replace("\\", "\\\\").replace('"', '\\"')
    script = f'display notification "{esc(message)}" with title "SlackTracker" subtitle "{esc(title)}"'
    if sound:
        script += f' sound name "{sound}"'
    threading.Thread(
        target=lambda: subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5),
        daemon=True,
    ).start()


# -------------------- Markdown log --------------------

def day_heading(day: date) -> str:
    return f"## {day.isoformat()} · {day.strftime('%A')}"


def period_row(period: dict) -> str:
    start = datetime.fromisoformat(period["start"])
    end = datetime.fromisoformat(period["end"])
    end_text = end.strftime("%H:%M:%S")
    if end.date() != start.date():
        end_text += f" (+{(end.date() - start.date()).days}d)"
    paused = int(period.get("paused", 0))
    note = (period.get("note") or "").replace("|", "\\|").replace("\n", " ")
    return (
        f"| {start.strftime('%H:%M:%S')} | {end_text} | {fmt_duration(period['worked'])} | "
        f"{fmt_duration(paused) if paused else '—'} | {note} |"
    )


def day_section(day: date, rows: list) -> list:
    total = sum(parse_duration(row.split("|")[3]) for row in rows)
    count = len(rows)
    return [
        day_heading(day),
        "",
        TABLE_HEADER,
        TABLE_RULE,
        *rows,
        "",
        f"**Total:** {fmt_duration(total)} across {count} period{'s' if count != 1 else ''}",
    ]


def record_period(path: Path, period: dict) -> None:
    """Add a period to its day's table in the Markdown log, refreshing the day total.

    Rows already in the file are kept verbatim, so hand edits to notes survive.
    """
    day = datetime.fromisoformat(period["start"]).date()
    if path.exists():
        lines = path.read_text(encoding="utf-8").rstrip("\n").split("\n")
    else:
        lines = ["# Work Log", "", "_Tracked with SlackTracker._"]

    last_heading = max((i for i, line in enumerate(lines) if line.startswith("## ")), default=-1)
    rows = []
    if (
        last_heading >= 0
        and lines[last_heading].startswith(f"## {day.isoformat()}")
        and TABLE_HEADER in lines[last_heading:]
    ):
        rows = [
            line for line in lines[last_heading:]
            if line.startswith("| ") and line not in (TABLE_HEADER, TABLE_RULE)
        ]
        lines = lines[:last_heading]
        while lines and not lines[-1].strip():
            lines.pop()
    rows.append(period_row(period))
    lines += [""] + day_section(day, rows)

    tmp = path.with_suffix(".md.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)


# -------------------- AppKit helpers --------------------

def ns_color(rgb):
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(*rgb, 1.0)


def symbol(name: str, template: bool = True):
    try:
        image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
        if image is not None:
            image.setTemplate_(template)
        return image
    except Exception:
        return None


def styled(text: str, size: float, weight: float = 0.0, rgb=None, mono: bool = True):
    font = (
        NSFont.monospacedDigitSystemFontOfSize_weight_(size, weight)
        if mono else NSFont.systemFontOfSize_weight_(size, weight)
    )
    attrs = {NSFontAttributeName: font}
    if rgb is not None:
        attrs[NSForegroundColorAttributeName] = ns_color(rgb)
    return NSAttributedString.alloc().initWithString_attributes_(text, attrs)


def load_dfr_functions() -> dict:
    """Private DFRFoundation calls used to pin an item in the Touch Bar Control Strip."""
    funcs = {}
    try:
        bundle = NSBundle.bundleWithPath_("/System/Library/PrivateFrameworks/DFRFoundation.framework")
        objc.loadBundleFunctions(bundle, funcs, [
            ("DFRElementSetControlStripPresenceForIdentifier", b"v@Z"),
            ("DFRSystemModalShowsCloseBoxWhenFrontMost", b"vZ"),
        ])
    except Exception as exc:
        log_debug(f"DFRFoundation unavailable: {exc}")
    return funcs


# -------------------- Touch Bar host window (fallback) --------------------

if HAVE_APPKIT:
    class KeyablePanel(NSPanel):
        """Invisible panel that can become key so AppKit shows its Touch Bar."""

        def canBecomeKeyWindow(self):
            return True

        def canBecomeMainWindow(self):
            return True
else:
    KeyablePanel = None


class TouchBarHost:
    """Invisible key-capable window; only used when the system-modal Touch Bar API is missing."""

    def __init__(self):
        self.panel = None
        if not HAVE_APPKIT:
            return
        screen = NSScreen.mainScreen().visibleFrame()
        rect = NSMakeRect(screen.origin.x, screen.origin.y, 1, 1)
        self.panel = KeyablePanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False
        )
        self.panel.setLevel_(NSFloatingWindowLevel)
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setAlphaValue_(0.0)
        self.panel.setHasShadow_(False)
        self.panel.setReleasedWhenClosed_(False)
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setIgnoresMouseEvents_(True)
        self.panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )

    def present(self, touch_bar):
        if self.panel is None:
            return
        self.panel.setTouchBar_(touch_bar)
        try:
            NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
            NSApp.activateIgnoringOtherApps_(True)
            NSRunningApplication.currentApplication().activateWithOptions_(
                NSApplicationActivateIgnoringOtherApps
            )
        except Exception:
            pass
        self.panel.orderFrontRegardless()
        self.panel.makeKeyAndOrderFront_(None)
        log_debug("Touch Bar host presented (fallback)")


# -------------------- Touch Bar --------------------

if HAVE_TOUCHBAR:
    class TouchBarController(NSObject):
        """Control Strip button plus a full Touch Bar with timer and Start/Pause/Stop/Discard."""

        STRIP_ID = "com.slacktracker.strip"
        STATUS_ID = "com.slacktracker.status"
        TIMER_ID = "com.slacktracker.timer"
        INFO_ID = "com.slacktracker.info"
        PRIMARY_ID = "com.slacktracker.primary"
        STOP_ID = "com.slacktracker.stop"
        DISCARD_ID = "com.slacktracker.discard"

        def initWithTracker_(self, tracker):
            self = objc.super(TouchBarController, self).init()
            if self is None:
                return None
            self.tracker = tracker
            self.views = {}
            self.strip_button = None
            self.dfr = {}
            self.touch_bar = NSTouchBar.alloc().init()
            self.touch_bar.setDelegate_(self)
            self.touch_bar.setDefaultItemIdentifiers_([
                self.STATUS_ID,
                self.TIMER_ID,
                NSTouchBarItemIdentifierFixedSpaceSmall,
                self.INFO_ID,
                NSTouchBarItemIdentifierFlexibleSpace,
                self.PRIMARY_ID,
                self.STOP_ID,
                self.DISCARD_ID,
            ])
            return self

        # ----- building -----

        @objc.python_method
        def _label(self):
            label = NSTextField.labelWithString_("")
            label.setTextColor_(NSColor.whiteColor())
            return label

        @objc.python_method
        def _button(self, title, symbol_name, action, rgb):
            if title:
                button = NSButton.buttonWithTitle_image_target_action_(
                    title, symbol(symbol_name), self, action
                )
                button.setImagePosition_(7)  # NSImageLeading
            else:
                button = NSButton.buttonWithImage_target_action_(symbol(symbol_name), self, action)
            button.setButtonType_(NSButtonTypeMomentaryPushIn)
            button.setBezelStyle_(NSBezelStyleRounded)
            button.setFont_(NSFont.systemFontOfSize_weight_(14, 0.3))
            button.setContentTintColor_(NSColor.whiteColor())
            button.setBezelColor_(ns_color(rgb))
            return button

        def touchBar_makeItemForIdentifier_(self, touch_bar, identifier):
            identifier = str(identifier)
            item = NSCustomTouchBarItem.alloc().initWithIdentifier_(identifier)
            if identifier in (self.STATUS_ID, self.TIMER_ID, self.INFO_ID):
                view = self._label()
            elif identifier == self.PRIMARY_ID:
                view = self._button("Start", "play.fill", "primaryPressed:", GREEN)
            elif identifier == self.STOP_ID:
                view = self._button("Stop", "stop.fill", "stopPressed:", RED)
            elif identifier == self.DISCARD_ID:
                view = self._button("", "trash", "discardPressed:", GREY)
            else:
                return None
            self.views[identifier] = view
            item.setView_(view)
            self.update()
            return item

        @objc.python_method
        def install_control_strip(self) -> bool:
            """Pin a timer button in the Control Strip (right side of the Touch Bar)."""
            self.dfr = load_dfr_functions()
            set_presence = self.dfr.get("DFRElementSetControlStripPresenceForIdentifier")
            if set_presence is None or not hasattr(NSTouchBarItem, "addSystemTrayItem_"):
                return False
            try:
                item = NSCustomTouchBarItem.alloc().initWithIdentifier_(self.STRIP_ID)
                self.strip_button = NSButton.buttonWithTitle_image_target_action_(
                    "", symbol("timer"), self, "stripPressed:"
                )
                self.strip_button.setBezelStyle_(NSBezelStyleRounded)
                self.strip_button.setImagePosition_(7)
                self.strip_button.setContentTintColor_(NSColor.whiteColor())
                item.setView_(self.strip_button)
                self.strip_item = item  # keep a strong reference
                NSTouchBarItem.addSystemTrayItem_(item)
                set_presence(self.STRIP_ID, True)
                show_close = self.dfr.get("DFRSystemModalShowsCloseBoxWhenFrontMost")
                if show_close is not None:
                    show_close(True)
                self.update()
                return True
            except Exception as exc:
                log_debug(f"Control Strip install failed: {exc}")
                return False

        # ----- actions -----

        def stripPressed_(self, sender):
            self.tracker.present_touchbar(None)

        def primaryPressed_(self, sender):
            self.tracker.primary_action(None)
            self.tracker.schedule_touchbar_hide()

        def stopPressed_(self, sender):
            self.tracker.stop_timer(None)
            self.tracker.schedule_touchbar_hide()

        def discardPressed_(self, sender):
            self.tracker.discard_timer(None)
            self.tracker.schedule_touchbar_hide()

        # ----- presenting -----

        @objc.python_method
        def present(self) -> bool:
            self.update()
            try:
                NSTouchBar.presentSystemModalTouchBar_systemTrayItemIdentifier_(
                    self.touch_bar, self.STRIP_ID if self.strip_button else None
                )
                log_debug("Touch Bar presented")
                return True
            except Exception as exc:
                log_debug(f"System-modal Touch Bar unavailable: {exc}")
                return False

        @objc.python_method
        def minimize(self) -> None:
            try:
                NSTouchBar.minimizeSystemModalTouchBar_(self.touch_bar)
            except Exception:
                pass

        # ----- refresh -----

        @objc.python_method
        def update(self):
            t = self.tracker
            elapsed = t.elapsed()
            if t.is_paused:
                status, rgb = "PAUSED", AMBER
            elif t.is_running:
                status, rgb = "● REC", RED
            else:
                status, rgb = "READY", MUTED

            v = self.views
            if self.STATUS_ID in v:
                v[self.STATUS_ID].setAttributedStringValue_(styled(status, 11, 0.6, rgb, mono=False))
            if self.TIMER_ID in v:
                clock = fmt_clock(elapsed) if t.is_active else "0:00"
                v[self.TIMER_ID].setAttributedStringValue_(
                    styled(clock, 20, 0.35, AMBER if t.is_paused else WHITE)
                )
            if self.INFO_ID in v:
                if t.is_active:
                    info = f"since {t.started_at.strftime('%H:%M')}"
                    if t.note:
                        info += f" · {ellipsize(t.note, 22)}"
                else:
                    info = "tap Start to begin a period"
                v[self.INFO_ID].setAttributedStringValue_(styled(info, 12, 0.0, MUTED, mono=False))
            if self.PRIMARY_ID in v:
                button = v[self.PRIMARY_ID]
                if not t.is_active:
                    title, icon, colour = "Start", "play.fill", GREEN
                elif t.is_paused:
                    title, icon, colour = "Resume", "play.fill", GREEN
                else:
                    title, icon, colour = "Pause", "pause.fill", AMBER
                button.setTitle_(title)
                button.setImage_(symbol(icon))
                button.setBezelColor_(ns_color(colour))
            if self.STOP_ID in v:
                v[self.STOP_ID].setEnabled_(t.is_active)
                v[self.STOP_ID].setBezelColor_(ns_color(RED if t.is_active else GREY))
            if self.DISCARD_ID in v:
                v[self.DISCARD_ID].setEnabled_(t.is_active)

            if self.strip_button is not None:
                # The Control Strip slot is narrow: time only while active (colour = state).
                if t.is_active:
                    self.strip_button.setImagePosition_(0)  # NSNoImage
                    self.strip_button.setAttributedTitle_(
                        styled(fmt_clock(elapsed, with_seconds=elapsed < 3600), 14, 0.5, WHITE)
                    )
                    self.strip_button.setBezelColor_(ns_color(AMBER if t.is_paused else RED))
                else:
                    self.strip_button.setImage_(symbol("timer"))
                    self.strip_button.setImagePosition_(1)  # NSImageOnly
                    self.strip_button.setTitle_("")
                    self.strip_button.setBezelColor_(None)
else:
    TouchBarController = None


if HAVE_APPKIT:
    class SleepObserver(NSObject):
        """Receives macOS sleep/wake notifications so sleep time is not counted."""

        def initWithTracker_(self, tracker):
            self = objc.super(SleepObserver, self).init()
            if self is None:
                return None
            self.tracker = tracker
            return self

        def workspaceWillSleep_(self, notification):
            self.tracker.handle_sleep()

        def workspaceDidWake_(self, notification):
            self.tracker.handle_wake()
else:
    SleepObserver = None


# -------------------- App --------------------

class SlackTracker(rumps.App):
    def __init__(self):
        super().__init__("SlackTracker", title="⏱", quit_button=None)
        if HAVE_APPKIT:
            try:
                NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
                NSRunningApplication.currentApplication().hide()
            except Exception:
                pass

        self.current = None      # the period being timed, or None
        self.history = []        # recently logged periods (newest last)
        self.settings = dict(DEFAULT_SETTINGS)
        self.load_state()

        self._build_menu()

        self.touchbar_host = TouchBarHost()
        self.touchbar = None
        if HAVE_TOUCHBAR:
            try:
                self.touchbar = TouchBarController.alloc().initWithTracker_(self)
            except Exception as exc:
                log_debug(f"Touch Bar setup failed: {exc}")
        self._touchbar_requested = False  # set from hotkey/signal threads, consumed on main
        self._toggle_requested = False
        self._touchbar_hide_at = None
        self._launch_setup_done = False
        self._menu_signature = None
        self._command_down = False
        self._last_command_tap = 0.0
        self._global_command_monitor = None
        self._local_command_monitor = None
        self.sleep_observer = None

        self.ui_timer = rumps.Timer(self.ui_tick, 1)
        self.ui_timer.start()

        self._start_hotkey_listener()
        self._install_signal_hooks()
        self._install_sleep_observer()

    # ---------- menu ----------

    def _item(self, title, callback=None, icon=None, key=None):
        item = rumps.MenuItem(title, callback=callback, key=key)
        if icon and HAVE_APPKIT:
            image = symbol(icon)
            if image is not None:
                item._menuitem.setImage_(image)
        return item

    def _build_menu(self):
        self.status_item = self._item("Ready", icon="timer")
        self.detail_item = self._item("Start a period to begin timing")
        self.primary_item = self._item("Start Timer", self.primary_action, "play.fill")
        self.stop_item = self._item("Stop & Log", self.stop_timer, "stop.fill")
        self.note_item = self._item("Start with Note…", self.edit_note, "square.and.pencil")
        self.discard_item = self._item("Discard Period", self.discard_timer, "trash")
        self.today_item = self._item("Today", icon="calendar")
        self.copy_item = self._item("Copy Today's Summary", self.copy_summary, "doc.on.doc")

        self.sleep_setting = self._item("Pause While Mac Sleeps", self.toggle_setting)
        self.seconds_setting = self._item("Show Seconds in Menu Bar", self.toggle_setting)
        self.autohide_setting = self._item("Auto-hide Touch Bar Controls", self.toggle_setting)
        self.remind_setting = self._item("Remind Every 2 Hours", self.toggle_setting)
        self._setting_items = {
            "exclude_sleep": self.sleep_setting,
            "menu_seconds": self.seconds_setting,
            "touchbar_auto_hide": self.autohide_setting,
            "remind_hours": self.remind_setting,
        }
        settings = self._item("Settings", icon="gearshape")
        for item in self._setting_items.values():
            settings.add(item)
        self._sync_setting_checks()

        self.menu = [
            self.status_item,
            self.detail_item,
            None,
            self.primary_item,
            self.stop_item,
            self.note_item,
            self.discard_item,
            None,
            self.today_item,
            self.copy_item,
            self._item("Open Log File", self.open_log, "doc.text"),
            None,
            self._item("Show Touch Bar Controls", self.present_touchbar, "rectangle.bottomthird.inset.filled"),
            settings,
            self._item(f"About SlackTracker {__version__}", self.open_repo, "info.circle"),
            None,
            self._item("Quit SlackTracker", self.quit_app, "power", key="q"),
        ]

    def _sync_setting_checks(self):
        for key, item in self._setting_items.items():
            item.state = 1 if self.settings.get(key) else 0

    def toggle_setting(self, sender):
        key = next(k for k, item in self._setting_items.items() if item.title == sender.title)
        if key == "remind_hours":
            self.settings[key] = 0 if self.settings.get(key) else DEFAULT_SETTINGS[key]
        else:
            self.settings[key] = not self.settings.get(key)
        self._sync_setting_checks()
        self.save_state()
        self.refresh_ui()

    # ---------- state ----------

    @property
    def is_active(self) -> bool:
        return self.current is not None

    @property
    def is_paused(self) -> bool:
        return bool(self.current and self.current.get("paused_at"))

    @property
    def is_running(self) -> bool:
        return self.is_active and not self.is_paused

    @property
    def started_at(self):
        return datetime.fromisoformat(self.current["start"]) if self.current else None

    @property
    def note(self) -> str:
        return (self.current or {}).get("note", "")

    def load_state(self):
        try:
            state = json.loads(STATE_FILE.read_text())
        except Exception:
            return
        if "running_since" in state:  # previous single-field format
            state = {"current": {"start": state["running_since"], "paused": 0}}
        current = state.get("current")
        if current and current.get("start"):
            try:
                datetime.fromisoformat(current["start"])
                current.setdefault("paused", 0)
                self.current = current
            except Exception:
                pass
        self.history = list(state.get("history", []))[-HISTORY_LIMIT:]
        self.settings.update(state.get("settings", {}))

    def save_state(self) -> None:
        state = {"current": self.current, "history": self.history, "settings": self.settings}
        try:
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, indent=2))
            tmp.replace(STATE_FILE)
        except Exception as exc:
            log_debug(f"Could not save state: {exc}")

    def elapsed(self, now=None) -> int:
        if not self.current:
            return 0
        now = now or datetime.now()
        reference = datetime.fromisoformat(self.current["paused_at"]) if self.is_paused else now
        total = (reference - self.started_at).total_seconds() - int(self.current.get("paused", 0))
        return max(0, int(total))

    # ---------- timer actions ----------

    def primary_action(self, _):
        if not self.is_active:
            self.start_timer(None)
        elif self.is_paused:
            self.resume_timer(None)
        else:
            self.pause_timer(None)

    def toggle_timer(self, _):
        if self.is_active:
            self.stop_timer(None)
        else:
            self.start_timer(None)

    def start_timer(self, _, note: str = ""):
        if self.is_active:
            return
        now = datetime.now().replace(microsecond=0)
        self.current = {"start": now.isoformat(), "paused": 0, "note": note, "reminded": 0}
        self.save_state()
        log_debug(f"Timer started at {now.isoformat()}")
        self.refresh_ui()

    def pause_timer(self, _, auto: bool = False):
        if not self.is_running:
            return
        self.current["paused_at"] = datetime.now().replace(microsecond=0).isoformat()
        self.current["auto_paused"] = auto
        self.save_state()
        log_debug("Timer paused" + (" (sleep)" if auto else ""))
        self.refresh_ui()

    def resume_timer(self, _):
        if not self.is_paused:
            return
        now = datetime.now().replace(microsecond=0)
        paused_at = datetime.fromisoformat(self.current.pop("paused_at"))
        self.current.pop("auto_paused", None)
        self.current["paused"] = int(self.current.get("paused", 0)) + max(
            0, int((now - paused_at).total_seconds())
        )
        self.save_state()
        log_debug("Timer resumed")
        self.refresh_ui()

    def stop_timer(self, _):
        if not self.is_active:
            return
        if self.is_paused:
            self.resume_timer(None)  # fold the open pause into the paused total
        end = datetime.now().replace(microsecond=0)
        period = {
            "start": self.current["start"],
            "end": end.isoformat(),
            "worked": self.elapsed(end),
            "paused": int(self.current.get("paused", 0)),
            "note": self.current.get("note", ""),
        }
        self.current = None
        self.history = (self.history + [period])[-HISTORY_LIMIT:]
        self.save_state()
        try:
            record_period(LOG_FILE, period)
            log_debug(f"Timer stopped; logged {fmt_duration(period['worked'])}")
            start = datetime.fromisoformat(period["start"])
            notify(
                f"Logged {fmt_duration(period['worked'])}",
                f"{start.strftime('%H:%M')} → {end.strftime('%H:%M')}"
                + (f" · {period['note']}" if period["note"] else "")
                + f"  ·  Today: {fmt_short(self.today_total())}",
                sound="Glass",
            )
        except Exception as exc:
            log_debug(f"Failed to write log: {exc}")
            notify("Could not write the log", str(exc))
        self.refresh_ui()

    def discard_timer(self, _):
        if not self.is_active:
            return
        discarded = self.elapsed()
        self.current = None
        self.save_state()
        log_debug(f"Timer discarded ({fmt_duration(discarded)})")
        notify("Period discarded", f"{fmt_duration(discarded)} was not logged")
        self.refresh_ui()

    def edit_note(self, _):
        if HAVE_APPKIT:
            NSApp.activateIgnoringOtherApps_(True)
        window = rumps.Window(
            message="What are you working on? It's saved with this period in the log.",
            title="Period Note" if self.is_active else "Start with Note",
            default_text=self.note,
            ok="Save" if self.is_active else "Start",
            cancel="Cancel",
            dimensions=(320, 24),
        )
        response = window.run()
        if response.clicked != 1:
            return
        text = response.text.strip()
        if self.is_active:
            self.current["note"] = text
            self.save_state()
            self.refresh_ui()
        else:
            self.start_timer(None, note=text)

    # ---------- today ----------

    def today_periods(self) -> list:
        today = date.today()
        return [p for p in self.history if datetime.fromisoformat(p["start"]).date() == today]

    def today_total(self) -> int:
        return sum(int(p["worked"]) for p in self.today_periods())

    def copy_summary(self, _):
        periods = self.today_periods()
        if not periods:
            notify("Nothing to copy", "No periods logged today yet")
            return
        lines = [day_heading(date.today()), "", TABLE_HEADER, TABLE_RULE]
        lines += [period_row(p) for p in periods]
        lines += ["", f"**Total:** {fmt_duration(self.today_total())} across {len(periods)} "
                      f"period{'s' if len(periods) != 1 else ''}"]
        board = NSPasteboard.generalPasteboard()
        board.clearContents()
        board.setString_forType_("\n".join(lines), NSPasteboardTypeString)
        notify("Copied today's summary", f"{len(periods)} periods · {fmt_short(self.today_total())}")

    # ---------- hotkey ----------

    def _start_hotkey_listener(self):
        if self._start_double_command_listener():
            log_debug("Double-Command shortcut registered")
        else:
            log_debug("Double-Command shortcut unavailable")
        if self._start_carbon_hotkey_listener():
            return
        self._start_pynput_hotkey_listener()

    def _start_pynput_hotkey_listener(self) -> None:
        if not HAVE_PYNPUT:
            return

        def show():
            self._touchbar_requested = True

        def toggle():
            self._toggle_requested = True

        def runner():
            try:
                with pkeyboard.GlobalHotKeys({
                    PYNPUT_HOTKEYS["show"]: show,
                    PYNPUT_HOTKEYS["toggle"]: toggle,
                }) as h:
                    h.join()
            except Exception:
                pass

        threading.Thread(target=runner, daemon=True).start()

    def _start_double_command_listener(self) -> bool:
        if not HAVE_APPKIT:
            return False

        def handle_flags(event):
            try:
                flags = int(event.modifierFlags())
                command_down = bool(flags & NSEventModifierFlagCommand)
                if command_down and not self._command_down:
                    now = monotonic()
                    if now - self._last_command_tap <= DOUBLE_COMMAND_SECONDS:
                        log_debug("Double-Command activated")
                        self._last_command_tap = 0.0
                        self._touchbar_requested = True
                    else:
                        self._last_command_tap = now
                self._command_down = command_down
            except Exception as exc:
                log_debug(f"Double-Command handler failed: {exc}")
            return event

        try:
            self._global_command_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                NSEventMaskFlagsChanged, handle_flags
            )
            self._local_command_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                NSEventMaskFlagsChanged, handle_flags
            )
            return self._global_command_monitor is not None or self._local_command_monitor is not None
        except Exception as exc:
            log_debug(f"Double-Command setup failed: {exc}")
            return False

    def _start_carbon_hotkey_listener(self) -> bool:
        if os.uname().sysname != "Darwin":
            return False

        class EventTypeSpec(ctypes.Structure):
            _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]

        class EventHotKeyID(ctypes.Structure):
            _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]

        def fourcc(value: str) -> int:
            return int.from_bytes(value.encode("ascii"), "big")

        try:
            carbon = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/Carbon.framework/Carbon"
            )
            self._carbon = carbon
            handler_type = ctypes.CFUNCTYPE(
                ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
            )
            carbon.GetEventParameter.argtypes = [
                ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p,
            ]

            def handler(next_handler, event, user_data):
                hotkey = EventHotKeyID()
                carbon.GetEventParameter(
                    event, fourcc("----"), fourcc("hkid"), None,
                    ctypes.sizeof(hotkey), None, ctypes.byref(hotkey),
                )
                if hotkey.id == HOTKEY_TOGGLE[0]:
                    log_debug("Start/stop hotkey activated")
                    self._toggle_requested = True
                else:
                    log_debug("Touch Bar hotkey activated")
                    self._touchbar_requested = True
                return 0

            self._carbon_hotkey_handler = handler_type(handler)
            event_spec = EventTypeSpec(fourcc("keyb"), 5)  # kEventHotKeyPressed

            carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
            target = carbon.GetApplicationEventTarget()

            carbon.InstallEventHandler.argtypes = [
                ctypes.c_void_p,
                handler_type,
                ctypes.c_uint32,
                ctypes.POINTER(EventTypeSpec),
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
            ]
            self._carbon_event_handler_ref = ctypes.c_void_p()
            status = carbon.InstallEventHandler(
                target,
                self._carbon_hotkey_handler,
                1,
                ctypes.byref(event_spec),
                None,
                ctypes.byref(self._carbon_event_handler_ref),
            )
            if status != 0:
                log_debug(f"Carbon InstallEventHandler failed: {status}")
                return False

            carbon.RegisterEventHotKey.argtypes = [
                ctypes.c_uint32,
                ctypes.c_uint32,
                EventHotKeyID,
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_void_p),
            ]
            self._carbon_hotkey_refs = []
            for hotkey_id, keycode, label in (HOTKEY_SHOW, HOTKEY_TOGGLE):
                ref = ctypes.c_void_p()
                status = carbon.RegisterEventHotKey(
                    keycode, CARBON_MODIFIERS, EventHotKeyID(fourcc("SlTk"), hotkey_id),
                    target, 0, ctypes.byref(ref),
                )
                if status != 0:
                    log_debug(f"Carbon RegisterEventHotKey failed for {label}: {status}")
                    return False
                self._carbon_hotkey_refs.append(ref)
                log_debug(f"Carbon hotkey registered: {label}")
            return True
        except Exception as exc:
            log_debug(f"Carbon hotkey setup failed: {exc}")
            return False

    def _install_sleep_observer(self) -> None:
        if not HAVE_APPKIT or SleepObserver is None:
            return
        try:
            self.sleep_observer = SleepObserver.alloc().initWithTracker_(self)
            center = NSWorkspace.sharedWorkspace().notificationCenter()
            center.addObserver_selector_name_object_(
                self.sleep_observer, "workspaceWillSleep:", NSWorkspaceWillSleepNotification, None,
            )
            center.addObserver_selector_name_object_(
                self.sleep_observer, "workspaceDidWake:", NSWorkspaceDidWakeNotification, None,
            )
        except Exception:
            self.sleep_observer = None

    def handle_sleep(self) -> None:
        if self.settings.get("exclude_sleep") and self.is_running:
            self.pause_timer(None, auto=True)

    def handle_wake(self) -> None:
        if self.is_paused and self.current.get("auto_paused"):
            self.resume_timer(None)

    def _install_signal_hooks(self) -> None:
        try:
            signal.signal(signal.SIGUSR1, self._handle_show_signal)
            signal.signal(signal.SIGUSR2, self._handle_toggle_signal)
        except Exception:
            pass

    def _handle_show_signal(self, signum, frame) -> None:
        log_debug("SIGUSR1 Touch Bar request")
        self._touchbar_requested = True

    def _handle_toggle_signal(self, signum, frame) -> None:
        log_debug("SIGUSR2 start/stop request")
        self._toggle_requested = True

    # ---------- UI loop ----------

    def ui_tick(self, _):
        if not self._launch_setup_done:
            self._launch_setup_done = True
            self.hide_from_dock()
            if self.touchbar and self.touchbar.install_control_strip():
                log_debug("Control Strip timer installed")

        # Consume shortcut / signal requests on the main thread.
        if self._touchbar_requested:
            self._touchbar_requested = False
            self.present_touchbar(None)
        if self._toggle_requested:
            self._toggle_requested = False
            self.toggle_timer(None)
            self.schedule_touchbar_hide()
        if self._touchbar_hide_at and monotonic() >= self._touchbar_hide_at:
            self._touchbar_hide_at = None
            if self.touchbar:
                self.touchbar.minimize()

        self.check_reminder()
        self.refresh_ui()

    def check_reminder(self) -> None:
        hours = int(self.settings.get("remind_hours") or 0)
        if not hours or not self.is_running:
            return
        due = self.elapsed() // (hours * 3600)
        if due > int(self.current.get("reminded", 0)):
            self.current["reminded"] = due
            self.save_state()
            notify(
                f"Timer running for {fmt_short(self.elapsed())}",
                "Still working? Stop the timer from the menu bar or Touch Bar when you finish.",
                sound="Submarine",
            )

    def hide_from_dock(self) -> None:
        try:
            NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
            NSRunningApplication.currentApplication().hide()
        except Exception:
            pass
        try:
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    (
                        'tell application "System Events" to set visible of '
                        f'(first process whose unix id is {os.getpid()}) to false'
                    ),
                ],
                capture_output=True,
                timeout=3,
            )
        except Exception:
            pass

    def refresh_ui(self):
        elapsed = self.elapsed()
        self._refresh_status_item(elapsed)

        if self.is_active:
            clock = fmt_clock(elapsed)
            state = "Paused" if self.is_paused else "Recording"
            self.status_item.title = f"{state} · {clock}"
            detail = f"Started {self.started_at.strftime('%H:%M')}"
            paused = int(self.current.get("paused", 0))
            if paused:
                detail += f" · paused {fmt_short(paused)}"
            if self.note:
                detail += f" · {ellipsize(self.note, 30)}"
            self.detail_item.title = detail
        else:
            self.status_item.title = "Ready"
            self.detail_item.title = "Start a period to begin timing"

        last_logged = self.history[-1]["end"] if self.history else None
        signature = (self.is_active, self.is_paused, last_logged, date.today())
        if signature != self._menu_signature:
            self._menu_signature = signature
            self._refresh_actions()
            self._refresh_today()

        if self.touchbar:
            self.touchbar.update()

    def _refresh_status_item(self, elapsed: int) -> None:
        nsapp = getattr(self, "_nsapp", None)
        status_item = getattr(nsapp, "nsstatusitem", None)
        if status_item is None:
            return
        button = status_item.button()
        if self.is_active:
            clock = fmt_clock(elapsed, with_seconds=bool(self.settings.get("menu_seconds")))
            icon = "pause.circle" if self.is_paused else "record.circle"
            button.setImage_(symbol(icon))
            button.setImagePosition_(2)  # NSImageLeft
            button.setAttributedTitle_(styled(" " + clock, 13, 0.2, MUTED if self.is_paused else None))
        else:
            button.setImage_(symbol("timer"))
            button.setImagePosition_(1)  # NSImageOnly
            button.setTitle_("")

    def _refresh_actions(self) -> None:
        def set_action(item, title, icon, callback):
            item.title = title
            item.set_callback(callback)
            image = symbol(icon)
            if image is not None:
                item._menuitem.setImage_(image)

        self.status_item._menuitem.setImage_(symbol(
            "pause.circle" if self.is_paused else "record.circle" if self.is_active else "timer"
        ))
        if not self.is_active:
            set_action(self.primary_item, "Start Timer", "play.fill", self.primary_action)
        elif self.is_paused:
            set_action(self.primary_item, "Resume", "play.fill", self.primary_action)
        else:
            set_action(self.primary_item, "Pause", "pause.fill", self.primary_action)
        # rumps disables items whose callback is None.
        self.stop_item.set_callback(self.stop_timer if self.is_active else None)
        self.discard_item.set_callback(self.discard_timer if self.is_active else None)
        self.note_item.title = "Edit Note…" if self.is_active else "Start with Note…"

    def _refresh_today(self) -> None:
        periods = self.today_periods()
        total = sum(int(p["worked"]) for p in periods)
        if self.today_item._menu is not None:
            self.today_item.clear()
        if not periods:
            self.today_item.title = "Today · nothing logged yet"
            self.today_item.add(rumps.MenuItem("Stop a period to log it here"))
            self.copy_item.set_callback(None)
            return
        self.today_item.title = (
            f"Today · {fmt_short(total)} in {len(periods)} period{'s' if len(periods) != 1 else ''}"
        )
        for period in reversed(periods):
            start = datetime.fromisoformat(period["start"])
            end = datetime.fromisoformat(period["end"])
            label = f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')}   {fmt_short(period['worked'])}"
            if period.get("note"):
                label += f"   {ellipsize(period['note'], 28)}"
            self.today_item.add(rumps.MenuItem(label))
        self.copy_item.set_callback(self.copy_summary)

    # ---------- Touch Bar / menu actions ----------

    def present_touchbar(self, _):
        if not self.touchbar:
            log_debug("Touch Bar unavailable on this Mac or PyObjC install")
            return
        self._touchbar_hide_at = None
        if not self.touchbar.present():
            self.touchbar_host.present(self.touchbar.touch_bar)

    def schedule_touchbar_hide(self) -> None:
        if self.settings.get("touchbar_auto_hide"):
            self._touchbar_hide_at = monotonic() + TOUCHBAR_AUTO_HIDE_SECONDS

    def open_log(self, _):
        if not LOG_FILE.exists():
            LOG_FILE.write_text("# Work Log\n\n_Tracked with SlackTracker._\n")
        subprocess.run(["open", str(LOG_FILE)])

    def open_repo(self, _):
        subprocess.run(["open", REPO_URL])

    def quit_app(self, _):
        rumps.quit_application()


if __name__ == "__main__":
    SlackTracker().run()
