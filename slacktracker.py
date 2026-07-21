#!/usr/bin/env python3
"""
SlackTracker — macOS menu bar app.

- Detects when Slack.app is running.
- Starts a timer on first Slack detection for the 06:00-06:00 workday.
- At 06:00 local time: finalizes the previous workday and writes a Markdown log entry.
- Re-opening Slack in the same 06:00-06:00 workday continues that workday.
- Persists state so quitting/restarting the tracker doesn't lose your timer.
- Double-tapping Command presents a Touch Bar timer for the current workday.
"""

import os
import json
import threading
import subprocess
import ctypes
import signal
from datetime import datetime, date, timedelta
from pathlib import Path
from time import monotonic

import rumps

# --- AppKit / pynput are optional but recommended ---
try:
    from AppKit import (
        NSPanel, NSColor, NSFont, NSScreen, NSApp,
        NSBackingStoreBuffered,
        NSFloatingWindowLevel, NSMakeRect, NSWorkspace,
        NSWorkspaceWillSleepNotification, NSWorkspaceDidWakeNotification,
        NSWindowStyleMaskBorderless,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorFullScreenAuxiliary,
        NSApplicationActivationPolicyAccessory,
        NSApplicationActivateIgnoringOtherApps, NSRunningApplication,
        NSEvent, NSEventMaskFlagsChanged, NSEventModifierFlagCommand,
    )
    from Foundation import NSObject
    import objc
    HAVE_APPKIT = True
except Exception:
    HAVE_APPKIT = False
    NSObject = object

try:
    from AppKit import (
        NSTouchBar, NSCustomTouchBarItem, NSButton,
        NSButtonTypeMomentaryPushIn, NSBezelStyleRounded,
    )
    HAVE_TOUCHBAR = True
except Exception:
    HAVE_TOUCHBAR = False

try:
    from pynput import keyboard as pkeyboard
    HAVE_PYNPUT = True
except Exception:
    HAVE_PYNPUT = False


HOME = Path.home()
LOG_FILE = HOME / "SlackWorkLog.md"
STATE_FILE = HOME / ".slacktracker_state.json"
POLL_SECONDS = 15
WORKDAY_START_HOUR = 6
FALLBACK_HOTKEY = "<ctrl>+<alt>+<cmd>+t"  # pynput fallback combo
CARBON_HOTKEY_KEYCODE = 17  # ANSI T
CARBON_HOTKEY_MODIFIERS = 0x0100 | 0x0800 | 0x1000  # cmdKey | optionKey | controlKey
DOUBLE_COMMAND_SECONDS = 0.45


def slack_running() -> bool:
    try:
        out = subprocess.run(
            ["pgrep", "-x", "Slack"],
            capture_output=True, text=True, timeout=3,
        )
        return out.returncode == 0
    except Exception:
        return False


def quit_slack() -> None:
    try:
        subprocess.run(
            ["osascript", "-e", 'tell application "Slack" to quit'],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass


def fmt_duration(seconds: int) -> str:
    h, rem = divmod(max(0, int(seconds)), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def workday_for(moment: datetime) -> str:
    day = moment.date()
    if moment.hour < WORKDAY_START_HOUR:
        day -= timedelta(days=1)
    return day.isoformat()


def workday_start(day_iso: str) -> datetime:
    day = date.fromisoformat(day_iso)
    return datetime(day.year, day.month, day.day, WORKDAY_START_HOUR)


def hour_start(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


def log_debug(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


# -------------------- Touch Bar host window --------------------

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
    """Invisible key-capable window used only to host Touch Bar content."""

    def __init__(self):
        self.panel = None
        if not HAVE_APPKIT:
            return
        self._build()

    def _build(self):
        w, h = 1, 1
        screen = NSScreen.mainScreen().visibleFrame()
        x = screen.origin.x
        y = screen.origin.y
        rect = NSMakeRect(x, y, w, h)

        self.panel = KeyablePanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False
        )
        self.panel.setLevel_(NSFloatingWindowLevel)
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(
            NSColor.clearColor()
        )
        self.panel.setAlphaValue_(0.0)
        self.panel.setHasShadow_(False)
        self.panel.setReleasedWhenClosed_(False)
        self.panel.setHidesOnDeactivate_(False)
        try:
            self.panel.setIgnoresMouseEvents_(True)
        except Exception:
            pass
        self.panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )

    def attach_touchbar(self, touch_bar) -> None:
        if self.panel is not None and hasattr(self.panel, "setTouchBar_"):
            self.panel.setTouchBar_(touch_bar)

    def present(self):
        if self.panel is None:
            log_debug("Touch Bar host unavailable")
            return
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
        log_debug("Touch Bar host presented")


if HAVE_TOUCHBAR:
    class TouchBarController(NSObject):
        """Touch Bar button that mirrors the current SlackTracker timer."""

        ITEM_ID = "com.slacktracker.timer"

        def initWithTracker_(self, tracker):
            self = objc.super(TouchBarController, self).init()
            if self is None:
                return None
            self.tracker = tracker
            self.button = None
            self.touch_bar = NSTouchBar.alloc().init()
            self.touch_bar.setDelegate_(self)
            self.touch_bar.setDefaultItemIdentifiers_([self.ITEM_ID])
            return self

        def touchBar_makeItemForIdentifier_(self, touch_bar, identifier):
            if str(identifier) != self.ITEM_ID:
                return None
            log_debug("Touch Bar item requested")
            item = NSCustomTouchBarItem.alloc().initWithIdentifier_(identifier)
            self.button = NSButton.buttonWithTitle_target_action_(
                "SlackTracker  |  --", self, "touchBarButtonPressed:"
            )
            self.button.setButtonType_(NSButtonTypeMomentaryPushIn)
            self.button.setBezelStyle_(NSBezelStyleRounded)
            self.button.setBordered_(True)
            self.button.setFont_(NSFont.boldSystemFontOfSize_(17))
            self.button.setToolTip_("SlackTracker workday timer")
            try:
                self.button.setContentTintColor_(NSColor.whiteColor())
            except Exception:
                pass
            try:
                self.button.setBezelColor_(
                    NSColor.colorWithCalibratedRed_green_blue_alpha_(0.15, 0.63, 0.34, 1.0)
                )
            except Exception:
                pass
            item.setView_(self.button)
            self.update()
            return item

        def touchBarButtonPressed_(self, sender):
            self.tracker.present_touchbar(None)

        def update(self):
            if self.button is None:
                return
            if self.tracker.state.get("day"):
                if self.tracker.is_sleeping:
                    status = "PAUSED"
                elif self.tracker.slack_is_running:
                    status = "SLACK"
                else:
                    status = "CLOSED"
                try:
                    workday = date.fromisoformat(self.tracker.state["day"])
                    day_label = f"{workday.strftime('%b')} {workday.day}"
                except Exception:
                    day_label = self.tracker.state["day"]
                title = (
                    f"{day_label}  |  {status}  |  "
                    f"{fmt_duration(self.tracker.current_elapsed(live=True))}"
                )
                if self.tracker.slack_is_running and not self.tracker.is_sleeping:
                    color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.15, 0.63, 0.34, 1.0)
                else:
                    color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.42, 0.42, 0.46, 1.0)
            else:
                title = "SLACKTRACKER  |  no active workday"
                color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.26, 0.36, 0.64, 1.0)
            self.button.setTitle_(title)
            try:
                self.button.setBezelColor_(color)
            except Exception:
                pass

        def present(self):
            self.update()
            try:
                NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
                NSApp.activateIgnoringOtherApps_(True)
                NSRunningApplication.currentApplication().activateWithOptions_(
                    NSApplicationActivateIgnoringOtherApps
                )
            except Exception:
                pass
            try:
                NSApp.setTouchBar_(self.touch_bar)
            except Exception:
                pass
            try:
                NSTouchBar.presentSystemModalFunctionBar_systemTrayItemIdentifier_(
                    self.touch_bar, self.ITEM_ID
                )
            except Exception:
                pass
            log_debug("Touch Bar present requested")
else:
    TouchBarController = None


if HAVE_APPKIT:
    class SleepObserver(NSObject):
        """Receives macOS sleep/wake notifications for timer checkpointing."""

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
        super().__init__("⏱", quit_button=None)
        if HAVE_APPKIT:
            try:
                NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
                NSRunningApplication.currentApplication().hide()
            except Exception:
                pass
        self.status_item = rumps.MenuItem("Status: idle")
        self.today_item = rumps.MenuItem("Today: 0m")
        self.menu = [
            self.status_item,
            self.today_item,
            None,
            rumps.MenuItem("Show Touch Bar Timer", callback=self.present_touchbar),
            rumps.MenuItem("Open log file", callback=self.open_log),
            rumps.MenuItem("Finish day now", callback=self.finish_now),
            None,
            rumps.MenuItem("Quit SlackTracker", callback=self.quit_app),
        ]
        self.state = self.load_state()
        self.slack_is_running = slack_running()
        self.is_sleeping = False

        self.touchbar_host = TouchBarHost()
        self.touchbar = None
        if HAVE_TOUCHBAR:
            try:
                self.touchbar = TouchBarController.alloc().initWithTracker_(self)
                if hasattr(NSApp, "setTouchBar_"):
                    NSApp.setTouchBar_(self.touchbar.touch_bar)
                self.touchbar_host.attach_touchbar(self.touchbar.touch_bar)
            except Exception:
                self.touchbar = None
        self._touchbar_requested = False  # set from hotkey thread, consumed on main
        self.sleep_observer = None
        self._command_down = False
        self._last_command_tap = 0.0
        self._global_command_monitor = None
        self._local_command_monitor = None
        self._hide_process_requested = True
        # Slack-polling timer (slow) and Touch Bar refresh timer (fast)
        self.poll_timer = rumps.Timer(self.tick, POLL_SECONDS)
        self.poll_timer.start()
        self.touchbar_timer = rumps.Timer(self.touchbar_tick, 1)
        self.touchbar_timer.start()

        self._start_hotkey_listener()
        self._install_signal_hooks()
        self._install_sleep_observer()
        self.tick(None)

    # ---------- state ----------

    def load_state(self) -> dict:
        if STATE_FILE.exists():
            try:
                state = json.loads(STATE_FILE.read_text())
                self.ensure_state_shape(state)
                return state
            except Exception:
                pass
        return {}

    def ensure_state_shape(self, state: dict) -> None:
        if not state.get("day"):
            return
        state.setdefault("hourly", {})
        state.setdefault("active_ranges", [])

    def save_state(self) -> None:
        try:
            STATE_FILE.write_text(json.dumps(self.state, indent=2))
        except Exception:
            pass

    # ---------- hotkey ----------

    def _start_hotkey_listener(self):
        if self._start_double_command_listener():
            log_debug("Double-Command shortcut registered")
        else:
            log_debug("Double-Command shortcut unavailable; using fallback chord")

        # Keep the old chord as a fallback; the primary shortcut is Command, Command.
        if self._start_carbon_hotkey_listener():
            return
        self._start_pynput_hotkey_listener()

    def _start_pynput_hotkey_listener(self) -> None:
        if not HAVE_PYNPUT:
            return
        def on_activate():
            # pynput callback runs on its own thread; defer UI work to main.
            self._touchbar_requested = True

        def runner():
            try:
                with pkeyboard.GlobalHotKeys({FALLBACK_HOTKEY: on_activate}) as h:
                    h.join()
            except Exception:
                pass

        t = threading.Thread(target=runner, daemon=True)
        t.start()

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

            def handler(next_handler, event, user_data):
                log_debug("Carbon hotkey activated")
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

            hotkey_id = EventHotKeyID(fourcc("SlTk"), 1)
            self._carbon_hotkey_ref = ctypes.c_void_p()
            carbon.RegisterEventHotKey.argtypes = [
                ctypes.c_uint32,
                ctypes.c_uint32,
                EventHotKeyID,
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_void_p),
            ]
            status = carbon.RegisterEventHotKey(
                CARBON_HOTKEY_KEYCODE,
                CARBON_HOTKEY_MODIFIERS,
                hotkey_id,
                target,
                0,
                ctypes.byref(self._carbon_hotkey_ref),
            )
            if status != 0:
                log_debug(f"Carbon RegisterEventHotKey failed: {status}")
                return False
            log_debug("Carbon hotkey registered: Ctrl+Option+Cmd+T")
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
                self.sleep_observer,
                "workspaceWillSleep:",
                NSWorkspaceWillSleepNotification,
                None,
            )
            center.addObserver_selector_name_object_(
                self.sleep_observer,
                "workspaceDidWake:",
                NSWorkspaceDidWakeNotification,
                None,
            )
        except Exception:
            self.sleep_observer = None

    def _install_signal_hooks(self) -> None:
        try:
            signal.signal(signal.SIGUSR1, self._handle_show_signal)
        except Exception:
            pass

    def _handle_show_signal(self, signum, frame) -> None:
        log_debug("SIGUSR1 Touch Bar request")
        self._touchbar_requested = True

    # ---------- core loop ----------

    def tick(self, _):
        now = datetime.now()
        current_workday = workday_for(now)

        running = slack_running()
        self.slack_is_running = running

        if self.state.get("day") and self.state["day"] != current_workday:
            self.rollover_workday(now, current_workday, running)

        if running and not self.is_sleeping:
            if "day" not in self.state:
                self.start_new_day(now, current_workday)
            else:
                if not self.add_active_delta(now):
                    self.state["sessions"] = self.state.get("sessions", 1) + 1
                self.state["last_seen"] = now.isoformat()
            self.save_state()

        self.refresh_menu()

    def touchbar_tick(self, _):
        # Consume shortcut requests on the main thread.
        if self._touchbar_requested:
            self._touchbar_requested = False
            self.present_touchbar(None)

        if self.touchbar:
            self.touchbar.update()
        if self._hide_process_requested:
            self._hide_process_requested = False
            self.hide_from_dock()

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

    def start_new_day(self, now: datetime, today: str) -> None:
        self.state = {
            "day": today,
            "start": now.isoformat(),
            "accumulated": 0,
            "last_seen": now.isoformat(),
            "sessions": 1,
            "first_open": now.isoformat(),
            "hourly": {},
            "active_ranges": [],
        }

    def rollover_workday(self, now: datetime, new_workday: str, running: bool) -> None:
        boundary = workday_start(new_workday)
        if running and not self.is_sleeping and self.add_active_delta(boundary):
            self.state["last_seen"] = boundary.isoformat()

        old_workday = self.state.get("day")
        self.finalize_day(reason="6am rollover")
        log_debug(f"Finalized workday {old_workday}; started {new_workday}")

        if running and not self.is_sleeping:
            self.start_new_day(boundary, new_workday)
            self.add_active_delta(now)
            self.state["last_seen"] = now.isoformat()
            self.save_state()

    def add_active_delta(self, now: datetime) -> bool:
        try:
            last = datetime.fromisoformat(self.state["last_seen"])
        except Exception:
            self.state["last_seen"] = now.isoformat()
            return True

        delta = (now - last).total_seconds()
        if delta < 0:
            return True
        if 0 <= delta <= POLL_SECONDS * 3:
            self.state["accumulated"] = int(self.state.get("accumulated", 0)) + int(delta)
            self.record_active_interval(last, now)
            return True
        return False

    def record_active_interval(self, start: datetime, end: datetime) -> None:
        if end <= start:
            return
        self.ensure_state_shape(self.state)
        self.record_active_range(start, end)
        self.record_hourly_buckets(start, end)

    def record_active_range(self, start: datetime, end: datetime) -> None:
        ranges = self.state.setdefault("active_ranges", [])
        start_iso = start.isoformat()
        end_iso = end.isoformat()
        if ranges:
            try:
                previous_end = datetime.fromisoformat(ranges[-1]["end"])
                gap = (start - previous_end).total_seconds()
                if 0 <= gap <= POLL_SECONDS * 3:
                    ranges[-1]["end"] = end_iso
                    return
            except Exception:
                pass
        ranges.append({"start": start_iso, "end": end_iso})

    def record_hourly_buckets(self, start: datetime, end: datetime) -> None:
        hourly = self.state.setdefault("hourly", {})
        cursor = start
        while cursor < end:
            next_hour = hour_start(cursor) + timedelta(hours=1)
            chunk_end = min(end, next_hour)
            seconds = int((chunk_end - cursor).total_seconds())
            if seconds > 0:
                key = hour_start(cursor).isoformat()
                hourly[key] = int(hourly.get(key, 0)) + seconds
            cursor = chunk_end

    def checkpoint_before_pause(self, now: datetime) -> None:
        if not self.state.get("day") or not self.slack_is_running:
            return
        self.add_active_delta(now)
        self.state["last_seen"] = now.isoformat()
        self.save_state()

    def handle_sleep(self) -> None:
        now = datetime.now()
        self.slack_is_running = slack_running()
        self.checkpoint_before_pause(now)
        self.is_sleeping = True
        self.refresh_menu()

    def handle_wake(self) -> None:
        now = datetime.now()
        self.is_sleeping = False
        self.slack_is_running = slack_running()
        if self.state.get("day"):
            self.state["last_seen"] = now.isoformat()
            self.save_state()
        self.refresh_menu()

    def current_elapsed(self, live: bool = False) -> int:
        base = int(self.state.get("accumulated", 0))
        if not live or not self.state.get("day") or not self.slack_is_running or self.is_sleeping:
            return base
        try:
            last = datetime.fromisoformat(self.state["last_seen"])
            extra = max(0, int((datetime.now() - last).total_seconds()))
            return base + min(extra, POLL_SECONDS * 3)
        except Exception:
            return base

    # ---------- finalize ----------

    def finalize_day(self, reason: str = "manual") -> None:
        if not self.state.get("day"):
            return
        day = self.state["day"]
        start = self.state.get("first_open") or self.state.get("start")
        end = self.state.get("last_seen") or datetime.now().isoformat()
        worked = int(self.state.get("accumulated", 0))
        sessions = self.state.get("sessions", 1)
        active_ranges = list(self.state.get("active_ranges", []))
        hourly = dict(self.state.get("hourly", {}))

        self.write_log_entry(day, start, end, worked, sessions, reason, active_ranges, hourly)
        self.state = {}
        self.save_state()

    def write_log_entry(self, day, start_iso, end_iso, worked_s, sessions, reason,
                        active_ranges=None, hourly=None):
        try:
            start_dt = datetime.fromisoformat(start_iso)
            end_dt = datetime.fromisoformat(end_iso)
        except Exception:
            start_dt = end_dt = datetime.now()
        active_ranges = active_ranges or []
        hourly = hourly or {}

        header_needed = not LOG_FILE.exists()
        with LOG_FILE.open("a", encoding="utf-8") as f:
            if header_needed:
                f.write("# Slack Work Log\n\n")
                f.write("Automatically generated by SlackTracker.\n\n")
            f.write(f"## {day}\n\n")
            f.write("- **Workday:** 06:00 to 06:00 next day\n")
            f.write(f"- **First opened Slack:** {start_dt.strftime('%H:%M:%S')}\n")
            f.write(f"- **Last activity:** {end_dt.strftime('%H:%M:%S')}\n")
            f.write(f"- **Time worked:** {fmt_duration(worked_s)} "
                    f"({worked_s // 60} min)\n")
            f.write(f"- **Sessions:** {sessions}\n")
            f.write(f"- **Closed by:** {reason}\n\n")
            self.write_range_log(f, active_ranges)
            self.write_hourly_log(f, hourly)

    def write_range_log(self, file_obj, active_ranges) -> None:
        if not active_ranges:
            return
        file_obj.write("### Active ranges\n\n")
        for item in active_ranges:
            try:
                start = datetime.fromisoformat(item["start"])
                end = datetime.fromisoformat(item["end"])
            except Exception:
                continue
            duration = int((end - start).total_seconds())
            if duration <= 0:
                continue
            file_obj.write(
                f"- {start.strftime('%H:%M')}-{end.strftime('%H:%M')}: "
                f"{fmt_duration(duration)}\n"
            )
        file_obj.write("\n")

    def write_hourly_log(self, file_obj, hourly) -> None:
        if not hourly:
            return
        file_obj.write("### Hourly breakdown\n\n")
        for key in sorted(hourly):
            try:
                start = datetime.fromisoformat(key)
            except Exception:
                continue
            seconds = int(hourly.get(key, 0))
            if seconds <= 0:
                continue
            end = start + timedelta(hours=1)
            file_obj.write(
                f"- {start.strftime('%H:%M')}-{end.strftime('%H:%M')}: "
                f"{fmt_duration(seconds)}\n"
            )
        file_obj.write("\n")

    # ---------- menu actions ----------

    def refresh_menu(self):
        if self.state.get("day"):
            worked = self.current_elapsed(live=True)
            self.title = "⏱"
            self.status_item.title = (
                "Status: tracking Slack" if self.slack_is_running else "Status: Slack closed"
            )
            self.today_item.title = f"Workday {self.state['day']}: {fmt_duration(worked)}"
        else:
            self.title = "⏱"
            self.status_item.title = "Status: idle"
            self.today_item.title = "Workday: 0m"

    def present_touchbar(self, _):
        log_debug("Touch Bar timer requested")
        if self.touchbar:
            self.touchbar_host.attach_touchbar(self.touchbar.touch_bar)
            self.touchbar_host.present()
            self.touchbar.present()
        else:
            log_debug("Touch Bar unavailable on this Mac or PyObjC install")

    def open_log(self, _):
        if not LOG_FILE.exists():
            LOG_FILE.write_text("# Slack Work Log\n\n(no entries yet)\n")
        subprocess.run(["open", str(LOG_FILE)])

    def finish_now(self, _):
        if self.state.get("day"):
            self.finalize_day(reason="manual")
            self.refresh_menu()
            rumps.notification("SlackTracker", "Day finalized",
                               f"Logged to {LOG_FILE.name}")
        else:
            rumps.notification("SlackTracker", "Nothing to log",
                               "No active Slack session today.")

    def quit_app(self, _):
        rumps.quit_application()


if __name__ == "__main__":
    SlackTracker().run()
