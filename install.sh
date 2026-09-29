#!/bin/bash
# SlackTracker installer for macOS — no admin rights needed.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$HOME/.slacktracker"
APP_BUNDLE="$APP_DIR/SlackTracker.app"
APP_MACOS="$APP_BUNDLE/Contents/MacOS"
PLIST="$HOME/Library/LaunchAgents/com.slacktracker.plist"

bold=$'\033[1m'; green=$'\033[32m'; red=$'\033[31m'; dim=$'\033[2m'; reset=$'\033[0m'
step() { echo "${bold}→${reset} $*"; }
fail() { echo "${red}✗${reset} $*" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || fail "SlackTracker runs on macOS only."

BASE_PY=""
for candidate in /usr/local/bin/python3 /opt/homebrew/bin/python3 /usr/bin/python3 "$(command -v python3 || true)"; do
  if [ -n "$candidate" ] && [ -x "$candidate" ]; then BASE_PY="$candidate"; break; fi
done
[ -n "$BASE_PY" ] || fail "python3 not found. Install Xcode Command Line Tools: xcode-select --install"

step "Installing SlackTracker to ${dim}$APP_DIR${reset}"
mkdir -p "$APP_DIR"
cp "$SRC_DIR/slacktracker.py" "$APP_DIR/slacktracker.py"

step "Creating Python environment ${dim}($("$BASE_PY" --version))${reset}"
"$BASE_PY" -m venv --clear "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/venv/bin/pip" install --quiet -r "$SRC_DIR/requirements.txt"

if command -v cc >/dev/null 2>&1; then
  step "Building app wrapper"
  mkdir -p "$APP_MACOS" "$APP_BUNDLE/Contents/Resources"
  cat > "$APP_MACOS/SlackTracker.c" <<EOF
#include <unistd.h>
#include <stdlib.h>

int main(void) {
    setenv("VIRTUAL_ENV", "$APP_DIR/venv", 1);
    setenv("PATH", "$APP_DIR/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin", 1);
    char *argv[] = { "$APP_DIR/venv/bin/python", "$APP_DIR/slacktracker.py", NULL };
    execv(argv[0], argv);
    return 1;
}
EOF
  cc "$APP_MACOS/SlackTracker.c" -o "$APP_MACOS/SlackTracker"
  rm -f "$APP_MACOS/SlackTracker.c"
  cat > "$APP_BUNDLE/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>com.slacktracker</string>
  <key>CFBundleName</key><string>SlackTracker</string>
  <key>CFBundleDisplayName</key><string>SlackTracker</string>
  <key>CFBundleExecutable</key><string>SlackTracker</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>2.0.0</string>
  <key>CFBundleVersion</key><string>2.0.0</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
EOF
fi

step "Registering login agent"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.slacktracker</string>
  <key>ProgramArguments</key>
  <array>
    <string>$APP_DIR/venv/bin/python</string>
    <string>$APP_DIR/slacktracker.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <!-- Restart after a crash, but respect Quit (a clean exit) until next login. -->
  <key>KeepAlive</key>
  <dict><key>SuccessfulExit</key><false/></dict>
  <key>StandardOutPath</key><string>$APP_DIR/out.log</string>
  <key>StandardErrorPath</key><string>$APP_DIR/err.log</string>
</dict>
</plist>
EOF
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

cat <<EOF

${green}${bold}✓ SlackTracker is running.${reset} Look for ⏱ in your menu bar.

  Start / Stop   ⏱ menu, the Touch Bar Control Strip, or ⌃⌥⌘S
  Touch Bar      tap the timer in the Control Strip, or double-tap ⌘
  Log file       ~/SlackWorkLog.md

  ${dim}Uninstall: bash "$SRC_DIR/uninstall.sh"${reset}
EOF
