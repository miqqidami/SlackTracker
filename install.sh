#!/bin/bash
# SlackTracker installer for macOS — no admin rights needed.
#
#   bash install.sh                        # installs "SlackTracker.app"
#   APP_NAME=TimeTracker bash install.sh   # same app, your own name
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="${APP_NAME:-SlackTracker}"
APP_DIR="$HOME/.slacktracker"
LABEL="com.slacktracker"
BUNDLE_ID="com.slacktracker.app"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC_DIR/slacktracker.py")"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

bold=$'\033[1m'; green=$'\033[32m'; red=$'\033[31m'; dim=$'\033[2m'; reset=$'\033[0m'
step() { echo "${bold}→${reset} $*"; }
fail() { echo "${red}✗${reset} $*" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || fail "SlackTracker runs on macOS only."
[[ "$APP_NAME" =~ ^[A-Za-z0-9][A-Za-z0-9\ ._-]*$ ]] || fail "APP_NAME may only use letters, digits, spaces, dots, dashes and underscores."

if [ -z "${APP_LOCATION:-}" ]; then
  if [ -w /Applications ]; then APP_LOCATION="/Applications"; else APP_LOCATION="$HOME/Applications"; fi
fi
APP_BUNDLE="$APP_LOCATION/$APP_NAME.app"

BASE_PY=""
for candidate in /usr/local/bin/python3 /opt/homebrew/bin/python3 /usr/bin/python3 "$(command -v python3 || true)"; do
  if [ -n "$candidate" ] && [ -x "$candidate" ]; then BASE_PY="$candidate"; break; fi
done
[ -n "$BASE_PY" ] || fail "python3 not found. Install Xcode Command Line Tools: xcode-select --install"

step "Installing $APP_NAME to ${dim}$APP_DIR${reset}"
mkdir -p "$APP_DIR"
cp "$SRC_DIR/slacktracker.py" "$APP_DIR/slacktracker.py"

step "Creating Python environment ${dim}($("$BASE_PY" --version))${reset}"
"$BASE_PY" -m venv --clear "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/venv/bin/pip" install --quiet -r "$SRC_DIR/requirements.txt"

step "Building ${bold}$APP_NAME.app${reset} in ${dim}$APP_LOCATION${reset}"
rm -rf "$APP_DIR/SlackTracker.app"  # hidden wrapper from older versions
if [ -f "$APP_DIR/app_path" ]; then
  previous="$(cat "$APP_DIR/app_path")"
  [ "$previous" != "$APP_BUNDLE" ] && [ -d "$previous" ] && rm -rf "$previous"
fi
mkdir -p "$APP_LOCATION"
rm -rf "$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/MacOS" "$APP_BUNDLE/Contents/Resources"
cp "$SRC_DIR/assets/AppIcon.icns" "$APP_BUNDLE/Contents/Resources/AppIcon.icns"
# Opening the app starts the menu bar timer, or shows its Touch Bar controls if it's already running.
cat > "$APP_BUNDLE/Contents/MacOS/launcher" <<'EOF'
#!/bin/bash
APP_DIR="$HOME/.slacktracker"
LABEL="com.slacktracker"
if pgrep -qf "$APP_DIR/slacktracker.py"; then
  pkill -USR1 -f "$APP_DIR/slacktracker.py"
elif ! launchctl kickstart "gui/$(id -u)/$LABEL" 2>/dev/null; then
  launchctl load "$HOME/Library/LaunchAgents/$LABEL.plist"
fi
EOF
chmod +x "$APP_BUNDLE/Contents/MacOS/launcher"
cat > "$APP_BUNDLE/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleName</key><string>$APP_NAME</string>
  <key>CFBundleDisplayName</key><string>$APP_NAME</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>LSUIElement</key><true/>
  <key>NSHumanReadableCopyright</key><string>MIT License · github.com/miqqidami/SlackTracker</string>
</dict>
</plist>
EOF
LSREGISTER=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
if [ -x "$LSREGISTER" ]; then "$LSREGISTER" -f "$APP_BUNDLE" || true; fi
mdimport "$APP_BUNDLE" 2>/dev/null || true
echo "$APP_BUNDLE" > "$APP_DIR/app_path"

step "Registering login agent"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <!-- Shows the app's name and icon in System Settings → General → Login Items. -->
  <key>AssociatedBundleIdentifiers</key><string>$BUNDLE_ID</string>
  <key>EnvironmentVariables</key>
  <dict><key>SLACKTRACKER_APP_NAME</key><string>$APP_NAME</string></dict>
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

${green}${bold}✓ $APP_NAME is running.${reset} Look for ⏱ in your menu bar.

  App            $APP_BUNDLE  (Spotlight, Launchpad, Finder)
  Start / Stop   ⏱ menu, the Touch Bar Control Strip, or ⌃⌥⌘S
  Touch Bar      tap the timer in the Control Strip, or double-tap ⌘
  Log file       ~/SlackWorkLog.md

  ${dim}Uninstall: bash "$SRC_DIR/uninstall.sh"${reset}
EOF
