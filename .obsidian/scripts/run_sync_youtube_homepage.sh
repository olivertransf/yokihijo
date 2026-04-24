#!/usr/bin/env bash
# Run sync_youtube_homepage_to_rss_dashboard.py with the project venv.
#
# Obsidian Shell Commands (command palette only — no vault reload / startup hook):
#   /bin/bash "{{!vault_path}}/.obsidian/scripts/run_sync_youtube_homepage.sh" --force
# Optional stale guard when you wrap this script yourself (not used by default palette command):
#   YOUTUBE_RSS_SYNC_IF_STALE_HOURS=20 bash "/.../run_sync_youtube_homepage.sh"
# Default is a visible Chrome window. To run headless (less reliable on some setups): YOUTUBE_RSS_SYNC_HEADLESS=1
# Default scraper uses the isolated YoutubeSeleniumChrome folder (works while normal Chrome is open).
# To use your real Google Chrome profile instead: Cmd+Q Chrome first, then:
#   YOUTUBE_RSS_CHROME=main bash "/.../run_sync_youtube_homepage.sh"
#
# Daily (macOS): copy com.yokihijo.youtube-rss-sync.plist.example into
# ~/Library/LaunchAgents/, set ProgramArguments to this script’s absolute path,
# then: launchctl load ~/Library/LaunchAgents/com.yokihijo.youtube-rss-sync.plist
#
# From the command palette (always run, ignore last sync):
#   bash "/.../run_sync_youtube_homepage.sh" --force
# Or: YOUTUBE_RSS_SYNC_FORCE=1 bash "/.../run_sync_youtube_homepage.sh"
#
# Quit Chrome before runs that use the on-disk YouTube session profile, or the
# scraper may fail (see youtube_homepage_links.py).

# Obsidian / GUI apps often invoke a non-bash shell or a minimal environment.
if [[ -z "${BASH_VERSION:-}" ]]; then
  exec /usr/bin/env bash "$0" "$@"
fi

set -euo pipefail

# $0 survives more launchers than ${BASH_SOURCE[0]} (e.g. some sh -c wrappers).
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STATE_FILE="$SCRIPT_DIR/.youtube_homepage_last_sync_epoch"
# Venv is outside iCloud — thousands of site-packages files were stalling iCloud sync.
# Override: YOUTUBE_RSS_VENV=/path/to/venv  (directory containing bin/python3)
_DEFAULT_VENV="${HOME}/Library/Application Support/YokihijoObsidian/venvs/.venv"
VENV_DIR="${YOUTUBE_RSS_VENV:-$_DEFAULT_VENV}"
PY="${VENV_DIR}/bin/python3"

if [[ ! -x "$PY" ]]; then
  echo "[youtube-rss-sync] No venv at ${PY}" >&2
  echo "[youtube-rss-sync] Create it: python3 -m venv \"${VENV_DIR}\" && \"${VENV_DIR}/bin/pip\" install -r \"${SCRIPT_DIR}/requirements-youtube-homepage.txt\"" >&2
  exit 2
fi

# Obsidian’s GUI environment often omits Homebrew paths.
export PATH="/usr/local/bin:/opt/homebrew/bin:${PATH:-/usr/bin:/bin:/usr/sbin:/sbin}"

force=0
case "${YOUTUBE_RSS_SYNC_FORCE:-}" in
1 | true | yes) force=1 ;;
esac
while [[ "${1:-}" == "--force" ]]; do
  force=1
  shift
done

if [[ -n "${YOUTUBE_RSS_SYNC_IF_STALE_HOURS:-}" && "$force" -eq 0 ]]; then
  threshold="${YOUTUBE_RSS_SYNC_IF_STALE_HOURS}"
  if [[ "$threshold" =~ ^[0-9]+$ ]] && [[ "$threshold" -gt 0 ]]; then
    now=$(date +%s)
    if [[ -f "$STATE_FILE" ]]; then
      IFS= read -r last <"$STATE_FILE" || last=""
      last="${last//[^0-9]/}"
      if [[ "$last" =~ ^[0-9]+$ ]] && ((last <= now)); then
        age_h=$(((now - last) / 3600))
        if ((age_h < threshold)); then
          echo "youtube-rss-sync: skip (last sync ${age_h}h ago, threshold ${threshold}h)"
          exit 0
        fi
      fi
    fi
  fi
fi

echo "[youtube-rss-sync] Starting (Chrome / Selenium may take a minute)…"
set +e
"$PY" "$SCRIPT_DIR/sync_youtube_homepage_to_rss_dashboard.py" "$@"
ec=$?
set -e
if [[ "$ec" -ne 0 ]]; then
  echo "[youtube-rss-sync] Failed (exit ${ec})" >&2
  exit "$ec"
fi

date +%s >"$STATE_FILE"
echo "[youtube-rss-sync] Finished OK."
