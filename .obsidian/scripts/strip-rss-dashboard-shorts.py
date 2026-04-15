#!/usr/bin/env python3
"""
Remove YouTube Shorts entries from RSS Dashboard cached data.

RSS Dashboard stores feeds in .obsidian/plugins/rss-dashboard/data.json.
Shorts are identified by /shorts/ in the item link.

Usage (from vault root):
  python3 .obsidian/scripts/strip-rss-dashboard-shorts.py
  python3 .obsidian/scripts/strip-rss-dashboard-shorts.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def is_youtube_short(link: str | None) -> bool:
    if not link:
        return False
    lower = link.lower()
    return (
        "youtube.com/shorts/" in lower
        or "youtu.be/shorts/" in lower
        or "m.youtube.com/shorts/" in lower
    )


def strip_shorts(path: Path, *, dry_run: bool) -> tuple[int, int, bool]:
    """
    Returns (removed_count, total_items_before, would_modify).
    If dry_run, would_modify is True iff shorts would be removed.
    """
    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    feeds = data.get("feeds")
    if not isinstance(feeds, list):
        raise ValueError("Invalid data: missing feeds array")

    total_before = 0
    removed = 0
    for feed in feeds:
        items = feed.get("items")
        if not isinstance(items, list):
            continue
        total_before += len(items)
        kept = []
        for item in items:
            link = item.get("link") if isinstance(item, dict) else None
            if is_youtube_short(link):
                removed += 1
            else:
                kept.append(item)
        feed["items"] = kept

    if dry_run or removed == 0:
        return removed, total_before, removed > 0

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"), ensure_ascii=False)

    return removed, total_before, True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many items would be removed without writing",
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=None,
        help="Path to data.json (default: vault .obsidian/plugins/rss-dashboard/data.json)",
    )
    args = parser.parse_args()

    # .obsidian/scripts/this.py -> vault
    vault = Path(__file__).resolve().parent.parent.parent
    path = args.data or vault / ".obsidian/plugins/rss-dashboard/data.json"

    if not path.is_file():
        print(f"Not found: {path}", file=sys.stderr)
        return 1

    try:
        removed, total_before, modified = strip_shorts(path, dry_run=args.dry_run)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1

    print(f"Feeds in file  Items: {total_before}  Shorts removed: {removed}")

    if args.dry_run:
        print("Dry run — no changes written.")
        return 0

    if not modified:
        print("No Shorts in cache — left unchanged.")
        return 0

    print(f"Updated {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
