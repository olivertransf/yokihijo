#!/usr/bin/env python3
"""Open Google Chrome with a persistent profile used only for YouTube automation.

Log in to YouTube (or Google) in that window, then quit Chrome. The session is
stored on disk under SESSION_DIR. Use the same path with youtube_homepage_links.py:

  python youtube_homepage_links.py --user-data-dir SESSION_DIR

Quit all Chrome windows using this profile before running the scraper (or you
will get a profile lock error).

  python3 open_chrome_youtube_session.py
  python3 open_chrome_youtube_session.py --session-dir ~/Library/Application Support/YouTubeSeleniumChrome
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

def _default_session_dir() -> Path:
    # Avoid iCloud paths (spaces + sync locks); user Library is stable on macOS/Linux.
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/YoutubeSeleniumChrome"
    if sys.platform == "win32":
        return Path.home() / "AppData/Local/YoutubeSeleniumChrome"
    return Path.home() / ".local/share/youtube-selenium-chrome"


_DEFAULT_SESSION = _default_session_dir()


def _chrome_executable() -> Path | None:
    if sys.platform == "darwin":
        p = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        if p.is_file():
            return p
    if sys.platform == "win32":
        for p in (
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        ):
            if p.is_file():
                return p
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        try:
            out = subprocess.check_output(["which", name], text=True, timeout=5).strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            continue
        if out:
            return Path(out)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Launch Chrome with a dedicated user-data-dir for YouTube login."
    )
    ap.add_argument(
        "--session-dir",
        type=Path,
        default=_DEFAULT_SESSION,
        help=f"Where to store this Chrome profile (default: {_DEFAULT_SESSION})",
    )
    ap.add_argument(
        "--url",
        default="https://www.youtube.com/",
        help="Page to open first.",
    )
    ap.add_argument(
        "--profile-directory",
        default="Default",
        help="Chrome profile subfolder name inside session-dir.",
    )
    args = ap.parse_args()

    session = args.session_dir.expanduser().resolve()
    session.mkdir(parents=True, exist_ok=True)

    chrome = _chrome_executable()
    if chrome is None:
        print("Could not find Google Chrome. Install it or edit the script path.", file=sys.stderr)
        return 1

    cmd = [
        str(chrome),
        f"--user-data-dir={session}",
        f"--profile-directory={args.profile_directory}",
        "--no-first-run",
        "--no-default-browser-check",
        args.url,
    ]
    print(f"# Session profile directory:\n#   {session}", file=sys.stderr)
    print("# Opening Chrome — log in to YouTube, then quit Chrome when finished.", file=sys.stderr)
    print("# After that, run:", file=sys.stderr)
    print(
        f'#   python3 youtube_homepage_links.py --user-data-dir "{session}"',
        file=sys.stderr,
    )
    print(file=sys.stderr)

    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except Exception as exc:
        print(f"Failed to start Chrome: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
