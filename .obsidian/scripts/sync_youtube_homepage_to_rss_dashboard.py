#!/usr/bin/env python3
"""Merge youtube_homepage_links.py output into RSS Dashboard data.json.

The plugin is patched with a synthetic feed (magic URL) and a sidebar row
\"YouTube home\" that shows only those items. \"All Feeds\" stays merged RSS
(synthetic feed is excluded from that merge).

Each run upserts `04 - Archives/YouTube homepage RSS/seen-videos.json` and
regenerates `Index.md` for every video id returned by the scraper. Video ids
marked read in RSS Dashboard (or already `\"read\": true` in seen-videos.json)
are omitted from the synthetic feed on the next sync so they do not reappear.

  cd .obsidian/scripts
  python3 sync_youtube_homepage_to_rss_dashboard.py
  # Default scraper uses the isolated YoutubeSeleniumChrome profile (--youtube-session).
  # Your real Google Chrome profile instead (must Cmd+Q Chrome first): YOUTUBE_RSS_CHROME=main python3 ...

  # Or: ./run_sync_youtube_homepage.sh  (venv in ~/Library/Application Support/YokihijoObsidian/venvs; see script header.)
  # Force an immediate run (ignore last-sync age): ./run_sync_youtube_homepage.sh --force
  # Default is visible Chrome. Headless (often flaky on newer Chrome): YOUTUBE_RSS_SYNC_HEADLESS=1 ./run_sync_youtube_homepage.sh --force

Quit Google Chrome before sync only when using YOUTUBE_RSS_CHROME=main (see youtube_homepage_links.py).
"""

from __future__ import annotations

import argparse
import json
import os
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
_GUID_YT_VIDEO = re.compile(r"^yt:video:([0-9A-Za-z_-]{11})\s*$")

_VAULT_ROOT = _SCRIPTS.parent.parent
_ARCHIVE_REL = Path("04 - Archives") / "YouTube homepage RSS"
_SEEN_JSON_NAME = "seen-videos.json"
_INDEX_MD_NAME = "Index.md"
_README_MD_NAME = "README.md"


def _video_id_from_url(url: str) -> str | None:
    m = _VIDEO_ID.search(url.strip())
    return m.group(1) if m else None


def _video_id_from_guid(guid: str) -> str | None:
    if not guid or not isinstance(guid, str):
        return None
    m = _GUID_YT_VIDEO.match(guid.strip())
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


def _ordered_rows(urls: list[str], skip_oembed: bool) -> list[tuple[str, str, str, str, int]]:
    """Return (url, video_id, title, author, index) for each valid watch URL."""
    rows: list[tuple[str, str, str, str, int]] = []
    j = 0
    for url in urls:
        vid = _video_id_from_url(url)
        if not vid:
            continue
        if skip_oembed:
            title, author = f"YouTube video ({vid})", "YouTube"
        else:
            title, author = _oembed_title(vid)
        rows.append((url, vid, title, author, j))
        j += 1
    return rows


def _item_dict(
    vid: str,
    title: str,
    author: str,
    seq: int,
    *,
    now: datetime,
    prev: dict | None,
) -> dict:
    tag_youtube = {"name": "YouTube", "color": "#ff0000"}
    pub = (now - timedelta(seconds=seq)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    item = {
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
    if prev and isinstance(prev, dict):
        for k in ("starred", "tags", "saved"):
            if k in prev:
                item[k] = prev[k]
    return item


def _read_video_ids_from_feed(items: list) -> set[str]:
    out: set[str] = set()
    for it in items:
        if not isinstance(it, dict) or not it.get("read"):
            continue
        vid = _video_id_from_url(it.get("link") or "") or _video_id_from_guid(it.get("guid") or "")
        if vid:
            out.add(vid)
    return out


def _read_video_ids_from_seen(seen: dict) -> set[str]:
    out: set[str] = set()
    raw = seen.get("videos")
    if not isinstance(raw, dict):
        return out
    for vid, meta in raw.items():
        if isinstance(meta, dict) and meta.get("read"):
            out.add(str(vid))
    return out


def _load_seen(path: Path) -> dict:
    if not path.is_file():
        return {"version": 1, "videos": {}}
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "videos": {}}
    if not isinstance(data, dict):
        return {"version": 1, "videos": {}}
    data.setdefault("version", 1)
    v = data.get("videos")
    if not isinstance(v, dict):
        data["videos"] = {}
    return data


def _old_items_by_video_id(items: list) -> dict[str, dict]:
    by_vid: dict[str, dict] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        vid = _video_id_from_url(it.get("link") or "") or _video_id_from_guid(it.get("guid") or "")
        if vid:
            by_vid[vid] = it
    return by_vid


def _upsert_seen_and_index(
    archive_dir: Path,
    rows: list[tuple[str, str, str, str, int]],
    read_ids: set[str],
    *,
    now: datetime,
    dry_run: bool,
) -> None:
    """Update seen-videos.json and regenerate Index.md under archive_dir."""
    seen_path = archive_dir / _SEEN_JSON_NAME
    index_path = archive_dir / _INDEX_MD_NAME
    readme_path = archive_dir / _README_MD_NAME
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if dry_run:
        return

    archive_dir.mkdir(parents=True, exist_ok=True)
    seen = _load_seen(seen_path)
    videos = seen.setdefault("videos", {})
    assert isinstance(videos, dict)

    for _url, vid, title, author, _i in rows:
        link = f"https://www.youtube.com/watch?v={vid}"
        prev = videos.get(vid) if isinstance(videos.get(vid), dict) else {}
        first = prev.get("first_seen") if isinstance(prev, dict) else None
        if not first or not isinstance(first, str):
            first = now_iso
        is_read = vid in read_ids
        videos[vid] = {
            "first_seen": first,
            "last_seen": now_iso,
            "title": title,
            "link": link,
            "author": author,
            "read": is_read,
        }

    tmp = seen_path.with_suffix(seen_path.suffix + ".tmp")
    tmp.write_text(json.dumps(seen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(seen_path)

    # Human-readable index (newest last_seen first)
    lines: list[str] = [
        "# YouTube homepage RSS — index",
        "",
        f"Auto-generated on **{now_iso}** by `sync_youtube_homepage_to_rss_dashboard.py`.",
        "",
        "Videos marked **read** in RSS Dashboard are dropped from the synthetic “YouTube home” feed on the **next** sync. To show one again, edit `"
        + _SEEN_JSON_NAME
        + "` in this folder and set `\"read\": false` for that video id (or remove the `read` key).",
        "",
        "## Entries (newest `last_seen` first)",
        "",
    ]
    entries: list[tuple[str, dict]] = []
    for vid, meta in videos.items():
        if isinstance(meta, dict):
            entries.append((str(vid), meta))
    entries.sort(key=lambda x: (x[1].get("last_seen") or ""), reverse=True)
    for vid, meta in entries:
        title = (meta.get("title") or vid).replace("\n", " ").strip()
        link = meta.get("link") or f"https://www.youtube.com/watch?v={vid}"
        ls = meta.get("last_seen") or ""
        rd = "**read**" if meta.get("read") else "unread"
        lines.append(f"- {ls} — [{title}]({link}) — `{vid}` — {rd}")
    lines.append("")
    index_path.write_text("\n".join(lines), encoding="utf-8")

    if not readme_path.is_file():
        readme_path.write_text(
            "\n".join(
                [
                    "# YouTube homepage RSS archive",
                    "",
                    "This folder is maintained by `.obsidian/scripts/sync_youtube_homepage_to_rss_dashboard.py`.",
                    "",
                    "- **`"
                    + _SEEN_JSON_NAME
                    + "`** — Upserted catalog of every video id seen on the homepage scrape (titles, links, `read` flag).",
                    "- **`"
                    + _INDEX_MD_NAME
                    + "`** — Regenerated list for quick browsing in Obsidian.",
                    "",
                    "Marking an item **read** in RSS Dashboard is picked up on the next sync: that video id is omitted from the synthetic feed and stored as `\"read\": true` here so it stays hidden even if `data.json` is rebuilt.",
                    "",
                ]
            ),
            encoding="utf-8",
        )


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
    ap.add_argument(
        "--archive-dir",
        type=Path,
        default=None,
        help=f"Vault folder for seen-videos.json + Index.md (default: {_VAULT_ROOT / _ARCHIVE_REL}).",
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
        # Default: isolated profile (same as earlier working setup). Main Chrome is opt-in — headless + real profile often crashes (chrome not reachable).
        _chrome = (os.environ.get("YOUTUBE_RSS_CHROME") or "session").strip().lower()
        _profile_flag = (
            "--use-my-chrome-profile"
            if _chrome in ("main", "google", "chrome", "real")
            else "--youtube-session"
        )
        _hint = (
            "quit Google Chrome (Cmd+Q) before sync — real profile cannot run while Chrome is open."
            if _profile_flag == "--use-my-chrome-profile"
            else "close any Chrome using YoutubeSeleniumChrome (e.g. from open_chrome_youtube_session.py) before sync."
        )
        print(f"# sync: Chrome mode {_chrome!r} → {_profile_flag}; {_hint}", file=sys.stderr)
        # Extra scrolls help load below-the-fold homepage shorts (RSS Dashboard shows full list for YT home).
        scraper_args = [
            _profile_flag,
            "--max-scrolls",
            "48",
            "--pause",
            "0.5",
            "--nav-timeout",
            "28",
            "--wait",
            "26",
        ]
        # Visible window by default (headless + uc often hits "chrome not reachable"). Opt in to headless:
        _hl = (os.environ.get("YOUTUBE_RSS_SYNC_HEADLESS") or "").strip().lower()
        if _hl in ("1", "true", "yes", "on"):
            scraper_args.append("--headless")

    data_path: Path = args.data_json
    if not data_path.is_file():
        print(f"Missing {data_path}", file=sys.stderr)
        return 2

    data = _load_data(data_path)
    feeds = data.get("feeds")
    if not isinstance(feeds, list):
        print("data.json: missing feeds array", file=sys.stderr)
        return 2

    archive_dir = args.archive_dir or (_VAULT_ROOT / _ARCHIVE_REL)
    seen_path = archive_dir / _SEEN_JSON_NAME
    seen = _load_seen(seen_path)
    idx_existing = next((i for i, f in enumerate(feeds) if isinstance(f, dict) and f.get("url") == MAGIC_FEED_URL), -1)
    old_items: list = []
    if idx_existing >= 0:
        old_feed = feeds[idx_existing]
        if isinstance(old_feed, dict):
            raw_items = old_feed.get("items")
            if isinstance(raw_items, list):
                old_items = raw_items

    read_ids = _read_video_ids_from_feed(old_items) | _read_video_ids_from_seen(seen)

    urls = _run_scraper(scraper_args)
    if not urls:
        print("No watch URLs from scraper.", file=sys.stderr)
        return 1

    rows = _ordered_rows(urls, skip_oembed=args.skip_oembed)
    if not rows:
        print("No valid video IDs parsed from URLs.", file=sys.stderr)
        return 1

    old_by_vid = _old_items_by_video_id(old_items)
    now = datetime.now(timezone.utc)
    items: list[dict] = []
    for _url, vid, title, author, seq in rows:
        if vid in read_ids:
            continue
        items.append(_item_dict(vid, title, author, seq, now=now, prev=old_by_vid.get(vid)))

    if not items:
        n_read = sum(1 for _u, v, *_r in rows if v in read_ids)
        print(
            f"All {len(rows)} homepage video(s) are marked read; writing empty synthetic feed "
            f"({n_read} skipped).",
            file=sys.stderr,
        )

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

    _upsert_seen_and_index(archive_dir, rows, read_ids, now=now, dry_run=args.dry_run)

    if args.dry_run:
        print(
            f"Would write {len(items)} homepage item(s) to feed {MAGIC_FEED_URL!r} "
            f"(scraped {len(rows)}, read/skipped {len(read_ids & {r[1] for r in rows})})."
        )
        return 0

    _atomic_write(data_path, data)
    skipped = len(rows) - len(items)
    msg = f"Wrote {len(items)} item(s) to {data_path} (feed {MAGIC_FEED_URL})."
    if skipped:
        msg += f" Skipped {skipped} read."
    print(msg)
    print(f"Archive: {archive_dir / _SEEN_JSON_NAME} (+ {_INDEX_MD_NAME})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
