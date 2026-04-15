#!/usr/bin/env bash
# Run sync_youtube_homepage_to_rss_dashboard.py with the project venv.
#
# Daily (macOS): copy com.yokihijo.youtube-rss-sync.plist.example into
# ~/Library/LaunchAgents/, set ProgramArguments to this script’s absolute path,
# then: launchctl load ~/Library/LaunchAgents/com.yokihijo.youtube-rss-sync.plist
#
# On Obsidian open: Shell commands plugin can run (cwd = vault root):
#   YOUTUBE_RSS_SYNC_IF_STALE_HOURS=20 .obsidian/scripts/run_sync_youtube_homepage.sh
# Event: “Obsidian starts” (on-layout-ready). Stale check limits rescrapes (launchd
# can still force a daily run at a fixed time).
#
# Quit Chrome before runs that use the on-disk YouTube session profile, or the
# scraper may fail (see youtube_homepage_links.py).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_FILE="$SCRIPT_DIR/.youtube_homepage_last_sync_epoch"
PY="$SCRIPT_DIR/.venv/bin/python3"
if [[ ! -x "$PY" ]]; then
  PY="python3"
fi

if [[ -n "${YOUTUBE_RSS_SYNC_IF_STALE_HOURS:-}" ]]; then
  threshold="${YOUTUBE_RSS_SYNC_IF_STALE_HOURS}"
  if [[ "$threshold" =~ ^[0-9]+$ ]] && [[ "$threshold" -gt 0 ]]; then
    now=$(date +%s)
    if [[ -f "$STATE_FILE" ]]; then
      last=$(<"$STATE_FILE")
      if [[ "$last" =~ ^[0-9]+$ ]] && (( last <= now )); then
        age_h=$(( (now - last) / 3600 ))
        if (( age_h < threshold )); then
          echo "youtube-rss-sync: skip (last sync ${age_h}h ago, threshold ${threshold}h)"
          exit 0
        fi
      fi
    fi
  fi
fi

if ! "$PY" "$SCRIPT_DIR/sync_youtube_homepage_to_rss_dashboard.py" "$@"; then
  exit 1
fi

date +%s >"$STATE_FILE"
