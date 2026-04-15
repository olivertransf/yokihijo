#!/usr/bin/env python3
"""
Watch RSS Dashboard data.json and run strip-rss-dashboard-shorts.py when it changes
(e.g. after a feed refresh). Uses only the Python standard library.

Run in a terminal and leave it open while you use Obsidian (from vault root):

  python3 .obsidian/scripts/watch-rss-dashboard-shorts.py

Optional: run in the background (macOS/Linux):

  nohup python3 .obsidian/scripts/watch-rss-dashboard-shorts.py >> /tmp/rss-strip-watch.log 2>&1 &

Stop with Ctrl+C (or kill the background process).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--debounce",
        type=float,
        default=0.75,
        metavar="SEC",
        help="Extra wait after the file stops changing (default: 0.75)",
    )
    parser.add_argument(
        "--poll",
        type=float,
        default=0.35,
        metavar="SEC",
        help="How often to check for changes (default: 0.35)",
    )
    parser.add_argument(
        "--run-on-start",
        action="store_true",
        help="Run the strip script once when the watcher starts",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    vault = script_dir.parent.parent
    data = vault / ".obsidian/plugins/rss-dashboard/data.json"
    strip = script_dir / "strip-rss-dashboard-shorts.py"

    if not strip.is_file():
        print(f"Missing: {strip}", file=sys.stderr)
        return 1

    if not data.is_file():
        print(f"RSS Dashboard data not found yet: {data}", file=sys.stderr)
        print("Open Obsidian with RSS Dashboard at least once, then restart this watcher.", file=sys.stderr)
        return 1

    print(f"Watching {data}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)

    last_processed = data.stat().st_mtime

    if args.run_on_start:
        subprocess.run([sys.executable, str(strip)], cwd=str(vault), check=False)
        last_processed = data.stat().st_mtime

    while True:
        time.sleep(args.poll)
        try:
            cur = data.stat().st_mtime
        except OSError:
            continue

        if cur == last_processed:
            continue

        # Change detected — wait until writes stop, then debounce
        while True:
            time.sleep(0.12)
            n = data.stat().st_mtime
            if n != cur:
                cur = n
                continue
            break

        time.sleep(args.debounce)
        if data.stat().st_mtime != cur:
            continue

        subprocess.run([sys.executable, str(strip)], cwd=str(vault), check=False)
        last_processed = data.stat().st_mtime


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        raise SystemExit(0)
