#!/bin/bash
# Removes SlackTracker. Your log (~/SlackWorkLog.md) is kept unless you pass --purge.
set -euo pipefail

APP_DIR="$HOME/.slacktracker"
PLIST="$HOME/Library/LaunchAgents/com.slacktracker.plist"

launchctl unload "$PLIST" 2>/dev/null || true
if [ -f "$APP_DIR/app_path" ]; then
  app="$(cat "$APP_DIR/app_path")"
  case "$app" in *.app) rm -rf "$app" ;; esac
fi
rm -rf "$APP_DIR" "$PLIST"

if [ "${1:-}" = "--purge" ]; then
  rm -f "$HOME/.slacktracker_state.json" "$HOME/SlackWorkLog.md"
  echo "✓ SlackTracker, its state and your work log were removed."
else
  echo "✓ SlackTracker removed. Your log is still at ~/SlackWorkLog.md (use --purge to delete it)."
fi
