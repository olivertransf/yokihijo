#!/usr/bin/env python3
"""Merge youtube_homepage_links.py output into RSS Dashboard data.json.

The plugin is patched with a synthetic feed (magic URL) and a sidebar row
\"YouTube home\" that shows only those items. \"All Feeds\" stays merged RSS
(synthetic feed is excluded from that merge).

  cd .obsidian/scripts
  python3 sync_youtube_homepage_to_rss_dashboard.py
  python3 sync_youtube_homepage_to_rss_dashboard.py --youtube-session --headless

  # Or: ./run_sync_youtube_homepage.sh  (uses .venv; see script header for daily
  # launchd + optional Obsidian startup via Shell commands plugin.)

Quit Chrome before running if using a on-disk profile (see youtube_homepage_links.py).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

MAGIC_FEED_URL = "__RSS_DASHBOARD_YOUTUBE_HOME__"
DEFAULT_FEED_TITLE = "YouTube homepage (Python)"

_SCRIPTS = Path(__file__).resolve().parent
_VAULT_OBSIDIAN = _SCRIPTS.parent
_DASHBOARD_DATA = _VAULT_OBSIDIAN / "plugins" / "rss-dashboard" / "data.json"
_SCRAPER = _SCRIPTS / "youtube_homepage_links.py"

_VIDEO_ID = re.compile(r"(?:v=|/watch\?v=|youtu\.be/)([0-9A-Za-z_-]{11})")


def _video_id_from_url(url: str) -> str | None:
    m = _VIDEO_ID.search(url.strip())
    return m.group(1) if m else None


def _oembed_title(video_id: str, timeout: float = 8.0) -> tuple[str, str]:
    """Return (title, author) from YouTube oEmbed."""
    watch = f"https://www.youtube.com/watch?v={video_id}"
    api = (
        "https://www.youtube.com/oembed?"
        + urllib.parse.urlencode({"url": watch, "format": "json"})
    )
    try:
        req = urllib.request.Request(
            api,
            headers={"User-Agent": "ObsidianRSSDashboardSync/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        title = (data.get("title") or "").strip() or f"Video {video_id}"
        author = (data.get("author_name") or "").strip() or "YouTube"
        return title, author
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return f"YouTube video ({video_id})", "YouTube"


def _run_scraper(extra_args: list[str]) -> list[str]:
    if not _SCRAPER.is_file():
        print(f"Missing scraper: {_SCRAPER}", file=sys.stderr)
        raise SystemExit(2)
    cmd = [sys.executable, str(_SCRAPER), *extra_args]
    proc = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        print(f"# scraper exit {proc.returncode}", file=sys.stderr)
        raise SystemExit(proc.returncode or 1)
    urls: list[str] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


def _build_items(urls: list[str], skip_oembed: bool) -> list[dict]:
    items: list[dict] = []
    now = datetime.now(timezone.utc)
    tag_youtube = {"name": "YouTube", "color": "#ff0000"}
    for i, url in enumerate(urls):
        vid = _video_id_from_url(url)
        if not vid:
            continue
        if skip_oembed:
            title, author = f"YouTube video ({vid})", "YouTube"
        else:
            title, author = _oembed_title(vid)
        pub = (now - timedelta(seconds=i)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        items.append(
            {
                "title": title,
                "link": f"https://www.youtube.com/watch?v={vid}",
                "description": "",
                "content": "",
                "pubDate": pub,
                "guid": f"yt:video:{vid}",
                "read": False,
                "starred": False,
                "tags": [tag_youtube],
                "feedTitle": DEFAULT_FEED_TITLE,
                "feedUrl": MAGIC_FEED_URL,
                "coverImage": f"https://img.youtube.com/vi/{vid}/maxresdefault.jpg",
                "summary": "",
                "author": author,
                "saved": False,
                "mediaType": "video",
                "explicit": False,
                "image": "",
                "videoId": vid,
            }
        )
    return items


def _load_data(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    bak = path.with_suffix(path.suffix + ".bak")
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if path.is_file():
        shutil.copy2(path, bak)
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Fetch YouTube homepage URLs and write them into rss-dashboard data.json."
    )
    ap.add_argument(
        "--data-json",
        type=Path,
        default=_DASHBOARD_DATA,
        help=f"Path to rss-dashboard data.json (default: {_DASHBOARD_DATA})",
    )
    ap.add_argument(
        "--skip-oembed",
        action="store_true",
        help="Do not fetch titles (faster; generic titles).",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Run scraper and print counts only; do not write data.json.",
    )
    ap.add_argument(
        "--data-status",
        action="store_true",
        help="Only read data.json: report whether the synthetic homepage feed exists (no Chrome).",
    )
    args, scraper_args = ap.parse_known_args()
    if args.data_status:
        path: Path = args.data_json
        if not path.is_file():
            print(f"Missing {path}", file=sys.stderr)
            return 2
        data = _load_data(path)
        feeds = data.get("feeds", [])
        hit = next((f for f in feeds if isinstance(f, dict) and f.get("url") == MAGIC_FEED_URL), None)
        if hit:
            n = len(hit.get("items") or [])
            print(
                f"OK: synthetic feed present with {n} item(s). "
                "In Obsidian RSS Dashboard click sidebar \"YouTube home\" (under All Feeds)."
            )
            return 0
        print(
            "No synthetic feed yet: add it by running this script without --data-status "
            f"(needs Selenium venv). URL must be {MAGIC_FEED_URL!r} in data.json.",
            file=sys.stderr,
        )
        return 1

    if not scraper_args:
        scraper_args = ["--youtube-session", "--headless"]

    urls = _run_scraper(scraper_args)
    if not urls:
        print("No watch URLs from scraper.", file=sys.stderr)
        return 1
    items = _build_items(urls, skip_oembed=args.skip_oembed)
    if not items:
        print("No valid video IDs parsed from URLs.", file=sys.stderr)
        return 1

    data_path: Path = args.data_json
    if not data_path.is_file():
        print(f"Missing {data_path}", file=sys.stderr)
        return 2

    data = _load_data(data_path)
    feeds = data.get("feeds")
    if not isinstance(feeds, list):
        print("data.json: missing feeds array", file=sys.stderr)
        return 2

    synthetic = {
        "title": DEFAULT_FEED_TITLE,
        "url": MAGIC_FEED_URL,
        "folder": "",
        "items": items,
        "mediaType": "video",
    }

    idx = next((i for i, f in enumerate(feeds) if f.get("url") == MAGIC_FEED_URL), -1)
    if idx >= 0:
        old = feeds[idx]
        if isinstance(old, dict):
            for k, v in old.items():
                if k not in synthetic and k not in ("items", "title", "url", "folder"):
                    synthetic[k] = v
        feeds[idx] = synthetic
    else:
        feeds.insert(0, synthetic)

    if args.dry_run:
        print(f"Would write {len(items)} homepage items to feed {MAGIC_FEED_URL!r}.")
        return 0

    _atomic_write(data_path, data)
    print(f"Wrote {len(items)} items to {data_path} (feed {MAGIC_FEED_URL}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
