#!/bin/bash
# Removes SlackTracker. Your log (~/SlackWorkLog.md) is kept unless you pass --purge.
set -euo pipefail

PLIST="$HOME/Library/LaunchAgents/com.slacktracker.plist"

launchctl unload "$PLIST" 2>/dev/null || true
rm -rf "$HOME/.slacktracker" "$PLIST"

if [ "${1:-}" = "--purge" ]; then
  rm -f "$HOME/.slacktracker_state.json" "$HOME/SlackWorkLog.md"
  echo "✓ SlackTracker, its state and your work log were removed."
else
  echo "✓ SlackTracker removed. Your log is still at ~/SlackWorkLog.md (use --purge to delete it)."
fi
