#!/bin/bash
# SlackTracker installer for macOS
set -e

APP_DIR="$HOME/.slacktracker"
APP_BUNDLE="$APP_DIR/SlackTracker.app"
APP_MACOS="$APP_BUNDLE/Contents/MacOS"
APP_RESOURCES="$APP_BUNDLE/Contents/Resources"
PLIST="$HOME/Library/LaunchAgents/com.slacktracker.plist"

echo "→ Installing SlackTracker to $APP_DIR"
mkdir -p "$APP_DIR"
cp "$(dirname "$0")/slacktracker.py" "$APP_DIR/slacktracker.py"

BASE_PY="/usr/local/bin/python3"
if [ ! -x "$BASE_PY" ]; then
  BASE_PY="/usr/bin/python3"
fi
if [ ! -x "$BASE_PY" ] && command -v python3 >/dev/null 2>&1; then
  BASE_PY="$(command -v python3)"
fi

if [ ! -x "$BASE_PY" ]; then
  echo "✗ python3 not found. Install Xcode Command Line Tools: xcode-select --install"
  exit 1
fi

echo "→ Creating Python virtualenv"
"$BASE_PY" -m venv --clear "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/venv/bin/pip" install --quiet rumps pyobjc pynput

echo "→ Creating hidden app wrapper"
mkdir -p "$APP_MACOS" "$APP_RESOURCES"
rm -f "$APP_MACOS/SlackTracker"
cat > "$APP_MACOS/SlackTracker.c" <<EOF
#include <unistd.h>
#include <stdlib.h>

int main(void) {
    setenv("VIRTUAL_ENV", "$APP_DIR/venv", 1);
    setenv("PATH", "$APP_DIR/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin", 1);
    char *argv[] = {
        "$APP_DIR/venv/bin/python",
        "$APP_DIR/slacktracker.py",
        NULL
    };
    execv(argv[0], argv);
    return 1;
}
EOF
cc "$APP_MACOS/SlackTracker.c" -o "$APP_MACOS/SlackTracker"
rm -f "$APP_MACOS/SlackTracker.c"
cat > "$APP_BUNDLE/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>com.slacktracker</string>
  <key>CFBundleName</key><string>SlackTracker</string>
  <key>CFBundleDisplayName</key><string>SlackTracker</string>
  <key>CFBundleExecutable</key><string>SlackTracker</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
EOF

echo "→ Installing launchd agent (auto-start at login)"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.slacktracker</string>
  <key>ProgramArguments</key>
  <array>
    <string>$APP_DIR/venv/bin/python</string>
    <string>$APP_DIR/slacktracker.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$APP_DIR/out.log</string>
  <key>StandardErrorPath</key><string>$APP_DIR/err.log</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo ""
echo "✓ Done. Look for ⏱ in your menu bar."
echo "  Log file:   ~/SlackWorkLog.md"
echo "  Workday:    06:00 to 06:00 next day"
echo "  Touch Bar:  press Command twice quickly  (shows workday + live timer)"
echo ""
echo "NOTE: Accessibility permission is only needed if macOS blocks Carbon"
echo "      hotkey registration and the app falls back to pynput."
echo "      System Settings → Privacy & Security → Accessibility"
echo "      ($APP_DIR/venv/bin/python)"
echo ""
echo "  Uninstall: launchctl unload $PLIST && rm -rf $APP_DIR $PLIST"
