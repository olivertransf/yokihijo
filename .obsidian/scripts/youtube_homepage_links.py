#!/usr/bin/env python3
"""Load YouTube in Chrome (optionally your profile) and print watch URLs from the homepage.

Close all Chrome windows before using --user-data-dir, or the profile may be locked.

  # Venv lives outside iCloud (see run_sync_youtube_homepage.sh). Example:
  #   python3 -m venv "$HOME/Library/Application Support/YokihijoObsidian/venvs/.venv"
  #   "$HOME/Library/Application Support/YokihijoObsidian/venvs/.venv/bin/pip" install -r requirements-youtube-homepage.txt
  #   source "$HOME/Library/Application Support/YokihijoObsidian/venvs/.venv/bin/activate"

  python youtube_homepage_links.py

  # Same as --user-data-dir ~/Library/Application Support/Google/Chrome (quit Chrome first)
  python youtube_homepage_links.py --use-my-chrome-profile

  # Attach to Chrome you started with --remote-debugging-port=9222 (often best on macOS)
  python youtube_homepage_links.py --debugger-address 127.0.0.1:9222

  # Try to load cookies from disk into a clean browser (often fails on macOS; see stderr)
  python youtube_homepage_links.py --use-my-chrome-profile --inject-cookies-from-chrome

  # Dedicated login profile (log in once via open_chrome_youtube_session.py, then scrape)
  python open_chrome_youtube_session.py
  python youtube_homepage_links.py --youtube-session
  python youtube_homepage_links.py --youtube-session --headless

  To push homepage videos into RSS Dashboard \"YouTube home\" sidebar row (patched plugin), run:
  python sync_youtube_homepage_to_rss_dashboard.py
"""

from __future__ import annotations

# undetected-chromedriver imports distutils before setuptools can install the shim.
try:
    import setuptools  # noqa: F401
except ImportError:
    pass

import argparse
import os
import re
import subprocess
import sys
import time
from http.cookiejar import Cookie
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_WATCH_ID_RE = re.compile(
    r'(?:v=|/watch\?v=|/embed/|"videoId"\s*:\s*")([0-9A-Za-z_-]{11})'
)
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

def _youtube_session_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/YoutubeSeleniumChrome"
    if sys.platform == "win32":
        return Path.home() / "AppData/Local/YoutubeSeleniumChrome"
    return Path.home() / ".local/share/youtube-selenium-chrome"


_YOUTUBE_SESSION_DIR = _youtube_session_dir()

def _import_uc():
    try:
        import undetected_chromedriver as uc

        return uc
    except Exception:
        return None


def _chrome_major_version() -> int | None:
    """Match ChromeDriver major to installed Chrome (avoids 146 vs 147 mismatch)."""
    candidates = (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    )
    for path in candidates:
        p = Path(path)
        if not p.is_file():
            continue
        try:
            out = subprocess.check_output(
                [str(p), "--version"], text=True, timeout=8, stderr=subprocess.DEVNULL
            )
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            continue
        m = re.search(r"(\d+)\.", out)
        if m:
            return int(m.group(1))
    for cmd in ("google-chrome", "chromium", "chrome"):
        try:
            out = subprocess.check_output(
                [cmd, "--version"], text=True, timeout=8, stderr=subprocess.DEVNULL
            )
            m = re.search(r"(\d+)\.", out)
            if m:
                return int(m.group(1))
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def _default_chrome_user_data_dir() -> Path | None:
    """Typical Chrome User Data paths (no guarantee the folder exists)."""
    home = Path.home()
    mac = home / "Library/Application Support/Google/Chrome"
    if mac.is_dir():
        return mac
    linux = home / ".config/google-chrome"
    if linux.is_dir():
        return linux
    return None


def _cookie_jar_from_chrome_profile(user_data_dir: Path, profile_directory: str):
    import browser_cookie3 as bc3

    cookie_file = user_data_dir / profile_directory / "Cookies"
    if not cookie_file.is_file():
        raise FileNotFoundError(f"Chrome Cookies DB not found: {cookie_file}")
    try:
        return bc3.chrome(cookie_file=str(cookie_file))
    except bc3.BrowserCookieError as exc:
        print(
            "\n# Cannot read Chrome cookies from disk (common on macOS: encrypted DB).",
            file=sys.stderr,
        )
        print(
            "# Options: (A) Quit Chrome, run with --use-my-chrome-profile, OR\n"
            "# (B) Start Chrome with --remote-debugging-port=9222 on your profile, then\n"
            "#     run with --debugger-address 127.0.0.1:9222\n",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc


def _inject_cookies_into_driver(
    driver: webdriver.Chrome, jar, max_per_domain: int = 400
) -> int:
    """Apply cookies from a CookieJar; must visit each registrable domain first."""
    try:
        cookies = list(jar)
    except TypeError:
        cookies = []

    usable: list[Cookie] = []
    for c in cookies:
        dom = (getattr(c, "domain", None) or "").lower()
        if not dom:
            continue
        d = dom.lstrip(".")
        if not any(
            x in d
            for x in ("google.com", "youtube.com", "youtu.be", "gstatic.com", "googlevideo.com")
        ):
            continue
        usable.append(c)

    if not usable:
        print("# No google/youtube cookies found in jar.", file=sys.stderr)
        return 0

    by_visit: dict[str, list[Cookie]] = {}
    for c in usable:
        dom = (getattr(c, "domain", "") or "").lstrip(".").lower()
        if dom.startswith("accounts."):
            key = "https://accounts.google.com/"
        elif "youtube.com" in dom:
            key = "https://www.youtube.com/"
        elif "google.com" in dom:
            key = "https://www.google.com/"
        else:
            key = "https://www.youtube.com/"
        by_visit.setdefault(key, []).append(c)

    added = 0
    for visit_url, batch in by_visit.items():
        print(f"# applying {len(batch)} cookie(s) after visiting {visit_url}", file=sys.stderr)
        driver.get(visit_url)
        time.sleep(0.4)
        for c in batch[:max_per_domain]:
            dom = getattr(c, "domain", "") or ""
            name = getattr(c, "name", "") or ""
            value = getattr(c, "value", "") or ""
            path = getattr(c, "path", None) or "/"
            secure = bool(getattr(c, "secure", False))
            if not name:
                continue
            payload: dict = {
                "name": name,
                "value": value,
                "path": path,
                "secure": secure,
            }
            if dom.startswith("."):
                payload["domain"] = dom
            else:
                payload["domain"] = dom
            exp = getattr(c, "expires", None)
            if exp not in (None, 0):
                try:
                    payload["expiry"] = int(exp)
                except (TypeError, ValueError):
                    pass
            try:
                driver.add_cookie(payload)
                added += 1
            except Exception as exc:
                print(f"# skip cookie {name!r} on {dom!r}: {exc}", file=sys.stderr)
    return added


def _log_tabs(driver: webdriver.Chrome, label: str) -> None:
    try:
        handles = driver.window_handles
    except Exception as exc:
        print(f"# {label}: could not list windows: {exc}", file=sys.stderr)
        return
    print(f"# {label}: {len(handles)} window(s)", file=sys.stderr)
    original = None
    try:
        original = driver.current_window_handle
    except Exception:
        pass
    for i, h in enumerate(handles):
        try:
            driver.switch_to.window(h)
            print(f"#   tab {i}: {driver.current_url!r}", file=sys.stderr)
        except Exception as exc:
            print(f"#   tab {i}: (error) {exc}", file=sys.stderr)
    if original:
        try:
            driver.switch_to.window(original)
        except Exception:
            if handles:
                driver.switch_to.window(handles[-1])


def _focus_best_window(driver: webdriver.Chrome) -> None:
    """Use the last tab (usually active); profile restore can open many tabs."""
    try:
        handles = driver.window_handles
        if not handles:
            return
        driver.switch_to.window(handles[-1])
        print(f"# focused tab index {len(handles) - 1} of {len(handles)}", file=sys.stderr)
    except Exception as exc:
        print(f"# focus window: {exc}", file=sys.stderr)


def _poll_youtube_url(driver: webdriver.Chrome) -> bool:
    try:
        return "youtube.com" in (driver.current_url or "").lower()
    except Exception:
        return False


def _navigate_to_youtube(driver: webdriver.Chrome, target_url: str, total_budget_s: float) -> None:
    """driver.get + fast URL polling; CDP/assign/tab fallbacks within one wall-clock budget."""
    deadline = time.time() + total_budget_s
    tick = 0.06

    def remaining() -> float:
        return max(0.0, deadline - time.time())

    def spin_until_youtube(label: str, phase_cap_s: float) -> bool:
        """Poll up to phase_cap_s (and never past deadline)."""
        end = min(time.time() + phase_cap_s, deadline)
        while time.time() < end:
            if _poll_youtube_url(driver):
                print(f"# landed ({label}): {driver.current_url!r}", file=sys.stderr)
                return True
            time.sleep(tick)
        return False

    print(f"# navigating to {target_url!r} (budget {total_budget_s:g}s)", file=sys.stderr)
    _focus_best_window(driver)
    print(f"# URL before get: {driver.current_url!r}", file=sys.stderr)

    driver.get(target_url)
    time.sleep(0.1)
    # Cap first poll so fallbacks still run inside the same total budget (~5s feels OK to fail)
    if spin_until_youtube("get", min(4.0, remaining())):
        return

    if remaining() <= 0:
        raise TimeoutError(
            f"No youtube.com in URL within budget (still {driver.current_url!r}). "
            "Increase --nav-timeout or fix Chrome/profile."
        )

    print(f"# still {driver.current_url!r}; CDP ({remaining():.1f}s left)", file=sys.stderr)
    try:
        driver.execute_cdp_cmd("Page.navigate", {"url": target_url})
    except Exception as exc:
        print(f"# CDP failed: {exc}", file=sys.stderr)
    time.sleep(0.1)
    if spin_until_youtube("cdp", min(2.5, remaining())):
        return

    if remaining() <= 0:
        raise TimeoutError(f"Navigation timeout (still {driver.current_url!r})")

    print("# location.assign", file=sys.stderr)
    try:
        driver.execute_script("window.location.assign(arguments[0]);", target_url)
    except Exception as exc:
        print(f"# assign failed: {exc}", file=sys.stderr)
    time.sleep(0.1)
    if spin_until_youtube("assign", min(2.5, remaining())):
        return

    try:
        handles = list(driver.window_handles)
    except Exception:
        handles = []
    for i, h in enumerate(handles[:6]):
        if remaining() <= 0:
            break
        try:
            driver.switch_to.window(h)
            print(f"# tab {i}: get() ({remaining():.1f}s left)", file=sys.stderr)
            driver.get(target_url)
            time.sleep(0.1)
            if spin_until_youtube(f"tab{i}", min(2.0, remaining())):
                return
        except Exception as exc:
            print(f"# tab {i}: {exc}", file=sys.stderr)

    raise TimeoutError(
        f"Could not open youtube.com (still {driver.current_url!r}). "
        "Try --fresh-tab, --nav-timeout 20, or another --profile-directory."
    )


def _open_fresh_tab_for_navigation(driver: webdriver.Chrome, enabled: bool) -> None:
    if not enabled:
        return
    try:
        print("# --fresh-tab: opening new tab", file=sys.stderr)
        driver.switch_to.new_window("tab")
    except Exception as exc:
        print(f"# new_window(tab) failed (continuing): {exc}", file=sys.stderr)


def _normalize_watch_url(href: str | None) -> str | None:
    if not href:
        return None
    parsed = urlparse(href)
    host = (parsed.netloc or "").lower()
    if "youtube.com" not in host:
        return None
    qs = parse_qs(parsed.query)
    vid = (qs.get("v") or [None])[0]
    if not vid:
        return None
    return f"https://www.youtube.com/watch?v={vid}"


def _watch_urls_from_page_source(driver: webdriver.Chrome) -> set[str]:
    """Fallback: YouTube embeds video ids in JSON/HTML even when headless hides <a> tags."""
    try:
        src = driver.page_source or ""
    except Exception:
        return set()
    out: set[str] = set()
    for m in _WATCH_ID_RE.finditer(src):
        vid = m.group(1)
        out.add(f"https://www.youtube.com/watch?v={vid}")
    return out


def _dismiss_youtube_or_google_consent(driver: webdriver.Chrome) -> bool:
    """Click common EU/Google consent controls so the real homepage can render."""
    js = r"""
    (function () {
      function visible(el) {
        if (!el) return false;
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && window.getComputedStyle(el).visibility !== "hidden";
      }
      const ids = ["introAgreeButton", "L2AGLb"];
      for (const id of ids) {
        const el = document.getElementById(id);
        if (visible(el)) {
          try {
            el.click();
            return true;
          } catch (err) {}
        }
      }
      const labels = /^(Accept all|I agree|Accept|Agree|Alle akzeptieren|Accepter tout|Tout accepter)$/i;
      const nodes = document.querySelectorAll("button, tp-yt-paper-button, ytd-button-renderer button, input[type='submit']");
      for (const el of nodes) {
        const t = (el.innerText || el.value || el.textContent || "").trim();
        if (!labels.test(t)) continue;
        if (!visible(el)) continue;
        try {
          el.click();
          return true;
        } catch (err) {}
      }
      return false;
    })();
    """
    try:
        clicked = bool(driver.execute_script(js))
        if clicked:
            time.sleep(1.8)
        return clicked
    except Exception:
        return False


def _collect_watch_links(driver: webdriver.Chrome) -> set[str]:
    out: set[str] = set()
    selectors = (
        'a[href*="/watch?v="]',
        "a#video-title[href*='/watch']",
        "a#thumbnail[href*='/watch']",
    )
    for sel in selectors:
        for el in driver.find_elements(By.CSS_SELECTOR, sel):
            try:
                href = el.get_attribute("href")
            except Exception:
                continue
            u = _normalize_watch_url(href)
            if u:
                out.add(u)
    out |= _watch_urls_from_page_source(driver)
    return out


def _scroll_collect(
    driver: webdriver.Chrome, max_scrolls: int, pause_s: float
) -> list[str]:
    collected: set[str] = set()
    stable_rounds = 0
    prev_count = -1

    for _ in range(max_scrolls):
        collected |= _collect_watch_links(driver)
        n = len(collected)
        if n == prev_count:
            stable_rounds += 1
            if stable_rounds >= 2:
                break
        else:
            stable_rounds = 0
        prev_count = n
        driver.execute_script(
            "window.scrollTo(0, document.documentElement.scrollHeight);"
        )
        time.sleep(pause_s)

    return sorted(collected)


def _chrome_option_args(
    user_data_dir: Path | None,
    profile_directory: str | None,
    headless: bool,
    debugger_address: str | None,
    *,
    use_uc_options: bool,
) -> object:
    """Build Chrome Options (selenium.Options or undetected_chromedriver.ChromeOptions)."""
    uc = _import_uc()
    if use_uc_options and uc is not None:
        opts = uc.ChromeOptions()
    else:
        opts = Options()
    opts.page_load_strategy = "none"
    if debugger_address:
        opts.add_experimental_option("debuggerAddress", debugger_address)
    if user_data_dir is not None:
        opts.add_argument(f"--user-data-dir={user_data_dir.resolve()}")
    if profile_directory:
        opts.add_argument(f"--profile-directory={profile_directory}")
    if headless:
        # undetected_chromedriver applies headless via Chrome(headless=True); avoid duplicate flags.
        if not use_uc_options:
            opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--lang=en-US")
    opts.add_argument("--window-size=1400,900")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    if not use_uc_options:
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
    return opts


def _build_driver(
    user_data_dir: Path | None,
    profile_directory: str | None,
    headless: bool,
    debugger_address: str | None,
    *,
    use_uc: bool,
) -> webdriver.Chrome:
    """Use undetected-chromedriver when allowed (YouTube often blocks plain Selenium)."""
    uc = _import_uc()
    if use_uc and uc is not None and debugger_address is None:
        opts = _chrome_option_args(
            user_data_dir,
            profile_directory,
            headless,
            None,
            use_uc_options=True,
        )
        vm = _chrome_major_version()
        if vm is not None:
            print(f"# using undetected-chromedriver (Chrome major {vm})", file=sys.stderr)
        else:
            print("# using undetected-chromedriver (Chrome version auto)", file=sys.stderr)
        kw: dict = {"options": opts, "use_subprocess": True, "headless": headless}
        if vm is not None:
            kw["version_main"] = vm
        try:
            return uc.Chrome(**kw)
        except Exception as exc:
            err = str(exc).lower()
            if kw.get("use_subprocess", True) and (
                "not reachable" in err or "cannot connect" in err or "session not created" in err
            ):
                print(
                    "# undetected-chromedriver: retrying with use_subprocess=False "
                    '(often fixes "chrome not reachable").',
                    file=sys.stderr,
                )
                kw2 = {**kw, "use_subprocess": False}
                try:
                    return uc.Chrome(**kw2)
                except Exception as exc2:
                    exc = exc2
                    err = str(exc2).lower()
            print(
                "# undetected-chromedriver failed to start Chrome.\n"
                "# If you use --use-my-chrome-profile: Cmd+Q Google Chrome, wait a few seconds, retry.\n"
                "# If you use --youtube-session: quit any Chrome window opened with that same session folder, "
                "or run without --headless.\n"
                "# Or attach to Chrome you started with --remote-debugging-port=9222: "
                "`--debugger-address 127.0.0.1:9222`.\n"
                f"# Underlying error: {exc}",
                file=sys.stderr,
            )
            if "user data directory" in err or "already in use" in err or "singleton" in err or "lock" in err:
                print(
                    "# (Often: profile directory locked by another Chrome using the same --user-data-dir.)",
                    file=sys.stderr,
                )
            raise

    opts = _chrome_option_args(
        user_data_dir,
        profile_directory,
        headless,
        debugger_address,
        use_uc_options=False,
    )
    return webdriver.Chrome(options=opts)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Print YouTube /watch?v= links from a loaded YouTube page (homepage by default)."
    )
    ap.add_argument(
        "--use-my-chrome-profile",
        action="store_true",
        help="Use this Mac/Linux default Chrome User Data path "
        "(same as ~/Library/Application Support/Google/Chrome on macOS).",
    )
    ap.add_argument(
        "--youtube-session",
        action="store_true",
        help=f"Use the manual-login folder created by open_chrome_youtube_session.py ({_YOUTUBE_SESSION_DIR}).",
    )
    ap.add_argument(
        "--user-data-dir",
        type=Path,
        metavar="DIR",
        help="Chrome user data directory (macOS: ~/Library/Application Support/Google/Chrome). "
        "Quit Chrome first unless using --debugger-address.",
    )
    ap.add_argument(
        "--profile-directory",
        default="Default",
        help="Profile folder name inside user-data-dir (default: Default).",
    )
    ap.add_argument(
        "--debugger-address",
        metavar="HOST:PORT",
        help="Attach to an already running Chrome (e.g. 127.0.0.1:9222). Start Chrome first with "
        "--remote-debugging-port=9222 and your normal --user-data-dir / --profile-directory.",
    )
    ap.add_argument(
        "--inject-cookies-from-chrome",
        action="store_true",
        help="Do not reuse your full profile; read cookies from your profile's Cookies DB and "
        "inject them (often fails on macOS encryption; try --use-my-chrome-profile or debugger).",
    )
    ap.add_argument(
        "--fresh-tab",
        action="store_true",
        help="Open a new tab before navigating (only if the default focused tab refuses to load).",
    )
    ap.add_argument(
        "--url",
        default="https://www.youtube.com/",
        help="Page to open (default: YouTube home).",
    )
    ap.add_argument(
        "--max-scrolls",
        type=int,
        default=40,
        metavar="N",
        help="Max scroll iterations (stops early if no new links).",
    )
    ap.add_argument(
        "--pause",
        type=float,
        default=0.45,
        metavar="SEC",
        help="Sleep between scrolls.",
    )
    ap.add_argument(
        "--headless",
        action="store_true",
        help="Run without a window. Uses undetected-chromedriver headless when available; "
        "session profiles (--youtube-session) work. If the feed is empty, run once without --headless.",
    )
    ap.add_argument(
        "--nav-timeout",
        type=float,
        default=22.0,
        metavar="SEC",
        help="Total seconds to reach youtube.com in the address bar (fail fast).",
    )
    ap.add_argument(
        "--wait",
        type=int,
        default=22,
        metavar="SEC",
        help="Max seconds to wait for first /watch?v= link after landing.",
    )
    ap.add_argument(
        "--no-uc",
        action="store_true",
        help="Disable undetected-chromedriver (plain Selenium only).",
    )
    args = ap.parse_args()

    chrome_user_data: Path | None = None
    if args.user_data_dir is not None:
        chrome_user_data = args.user_data_dir.expanduser()
    elif args.youtube_session:
        chrome_user_data = _YOUTUBE_SESSION_DIR
        print(
            f"# using YouTube session profile: {chrome_user_data}\n"
            "# (run open_chrome_youtube_session.py first if this folder is empty).",
            file=sys.stderr,
        )
    elif args.use_my_chrome_profile:
        env = (os.environ.get("CHROME_USER_DATA") or "").strip()
        if env:
            chrome_user_data = Path(env).expanduser()
        else:
            found = _default_chrome_user_data_dir()
            if found is None:
                print(
                    "# Could not find Chrome User Data dir. Set CHROME_USER_DATA or pass --user-data-dir.",
                    file=sys.stderr,
                )
                return 2
            chrome_user_data = found

    dbg = (args.debugger_address or "").strip() or None
    inject = bool(args.inject_cookies_from_chrome)

    if inject and dbg:
        print("# --inject-cookies-from-chrome ignored when --debugger-address is set.", file=sys.stderr)
        inject = False

    if dbg and chrome_user_data is not None:
        print(
            "# Note: --debugger-address attaches to your running Chrome profile; "
            "--user-data-dir is not passed to WebDriver.",
            file=sys.stderr,
        )

    if inject:
        driver_user_data: Path | None = None
        driver_profile: str | None = None
    elif dbg:
        driver_user_data = None
        driver_profile = None
    else:
        driver_user_data = chrome_user_data
        driver_profile = args.profile_directory

    uc = _import_uc()
    use_uc = not args.no_uc and uc is not None and dbg is None
    if not args.no_uc and uc is None:
        print(
            "# Install undetected-chromedriver for better YouTube compatibility: "
            "pip install undetected-chromedriver",
            file=sys.stderr,
        )

    driver = _build_driver(
        driver_user_data, driver_profile, args.headless, dbg, use_uc=use_uc
    )
    try:
        driver.set_page_load_timeout(25)
        target = str(args.url).strip() or "https://www.youtube.com/"

        if inject:
            if chrome_user_data is None:
                print(
                    "# --inject-cookies-from-chrome needs --user-data-dir or --use-my-chrome-profile.",
                    file=sys.stderr,
                )
                return 2
            print("# inject: loading Cookies DB from profile (may fail on macOS encryption).", file=sys.stderr)
            jar = _cookie_jar_from_chrome_profile(chrome_user_data, args.profile_directory)
            n = _inject_cookies_into_driver(driver, jar)
            print(f"# inject: applied ~{n} cookie field(s).", file=sys.stderr)

        _log_tabs(driver, "after start")
        _open_fresh_tab_for_navigation(driver, bool(args.fresh_tab))
        _log_tabs(driver, "after optional new tab")
        _navigate_to_youtube(driver, target, float(args.nav_timeout))
        # Headless often hydrates rich content late; consent walls also delay watch links.
        post_nav = 4.5 if args.headless else 0.25
        time.sleep(post_nav)
        try:
            driver.execute_script("window.scrollTo(0, 600);")
        except Exception:
            pass
        time.sleep(0.35)
        for attempt in range(3):
            if _dismiss_youtube_or_google_consent(driver):
                print("# dismissed a consent / cookie dialog (attempt %s)" % (attempt + 1), file=sys.stderr)
            try:
                WebDriverWait(driver, args.wait, poll_frequency=0.12).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'a[href*="/watch?v="]'))
                )
                break
            except TimeoutException:
                if attempt < 2:
                    print(
                        "# no watch links in DOM yet; retry after consent / extra wait.",
                        file=sys.stderr,
                    )
                    time.sleep(2.0)
                    _dismiss_youtube_or_google_consent(driver)
                else:
                    print(
                        "# no watch links in DOM yet; scrolling to collect (slow feed or consent).",
                        file=sys.stderr,
                    )
        urls = _scroll_collect(driver, args.max_scrolls, args.pause)
        if not urls:
            if _dismiss_youtube_or_google_consent(driver):
                print("# late consent click; re-scanning DOM once", file=sys.stderr)
            time.sleep(2.5)
            urls = sorted(_collect_watch_links(driver))
        if not urls:
            print(
                "# zero watch URLs — try: run once without --headless, complete any consent/sign-in, "
                "then retry; or --debugger-address 127.0.0.1:9222 with Chrome started manually; "
                "or extend --wait / --max-scrolls. Reinstall: pip install -r requirements-youtube-homepage.txt "
                "(Python 3.13+: setuptools<74; this script pre-imports setuptools for undetected-chromedriver).",
                file=sys.stderr,
            )
            return 1
        for u in urls:
            print(u)
        print(f"# urls: {len(urls)}", file=sys.stderr)
    finally:
        driver.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
