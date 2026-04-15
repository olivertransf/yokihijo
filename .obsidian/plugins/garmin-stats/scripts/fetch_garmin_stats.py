#!/usr/bin/env python3
"""Fetch Garmin Connect daily stats via pirate-garmin CLI, emit JSON for the Obsidian plugin.

Setup (one-time):
  1. pirate-garmin is installed via uv tool install — binary at ~/.local/bin/pirate-garmin
  2. First login requires browser/Playwright:
       uv tool install 'git+https://github.com/jeffton/pirate-garmin' --with playwright
       playwright install chromium
       pirate-garmin login --username EMAIL --password PASS   # use your account; never commit real values
  3. Subsequent runs reuse cached tokens at ~/.garmin/native-oauth2.json — no browser needed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import date


# ── pirate-garmin binary discovery ──────────────────────────────────────────

PIRATE_BIN_ENV = "PIRATE_GARMIN_BIN"
KNOWN_PATHS = [
    os.path.expanduser("~/.local/bin/pirate-garmin"),
    "/usr/local/bin/pirate-garmin",
    "/opt/homebrew/bin/pirate-garmin",
]


def find_pirate_bin(hint: str | None = None) -> str | None:
    if hint and os.path.isfile(hint):
        return hint
    explicit = os.environ.get(PIRATE_BIN_ENV)
    if explicit and os.path.isfile(explicit):
        return explicit
    found = shutil.which("pirate-garmin")
    if found:
        return found
    for path in KNOWN_PATHS:
        if os.path.isfile(path):
            return path
    return None


# ── subprocess helpers ───────────────────────────────────────────────────────

def _run(bin_path: str, *args: str, timeout: int = 60) -> object:
    result = subprocess.run(
        [bin_path, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    out = result.stdout.strip()
    if result.returncode != 0 and not out:
        raise RuntimeError(result.stderr.strip() or f"pirate-garmin exited {result.returncode}")
    if not out:
        raise RuntimeError("empty output from pirate-garmin")
    # Try full output as JSON first (pirate-garmin outputs pretty-printed multi-line JSON)
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        pass
    # Fallback: find the last single line that looks like JSON
    for line in reversed(out.splitlines()):
        stripped = line.strip()
        if stripped.startswith(("{", "[")):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                continue
    raise RuntimeError(f"no JSON in pirate-garmin output: {out[:300]}")


def get_endpoint(
    bin_path: str,
    key: str,
    path: dict[str, str] | None = None,
    query: dict[str, str] | None = None,
) -> object:
    args = ["get", key]
    for k, v in (path or {}).items():
        args += ["--path", f"{k}={v}"]
    for k, v in (query or {}).items():
        args += ["--query", f"{k}={v}"]
    return _run(bin_path, *args)


# ── response normalisation helpers ──────────────────────────────────────────

def extract_body_battery_list(raw: object) -> list | None:
    """Garmin wraps body-battery in various envelopes; return the values list."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("bodyBatteryValues", "dailyBodyBatteryValues", "values"):
            if isinstance(raw.get(key), list):
                return raw[key]
    return None


# ── main ─────────────────────────────────────────────────────────────────────

def emit(obj: object) -> None:
    print(json.dumps(obj, default=str))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="YYYY-MM-DD (default: today)")
    # --tokenstore accepted but ignored (pirate-garmin uses ~/.garmin/)
    parser.add_argument("--tokenstore", help=argparse.SUPPRESS)
    ns = parser.parse_args()

    today: str = ns.date or date.today().strftime("%Y-%m-%d")

    bin_path = find_pirate_bin()
    if not bin_path:
        emit({
            "ok": False,
            "error": "pirate_garmin_not_found",
            "message": (
                "pirate-garmin not found. "
                "Install: uv tool install 'git+https://github.com/jeffton/pirate-garmin' "
                "then login: pirate-garmin login --username EMAIL --password PASS"
            ),
        })
        sys.exit(1)

    # ── profile (display name for panel header) ──────────────────────────────
    display_name: str | None = None
    try:
        profile = _run(bin_path, "profile")
        if isinstance(profile, dict):
            display_name = (
                profile.get("displayName")
                or profile.get("userName")
                or profile.get("userInfo", {}).get("displayName") if isinstance(profile.get("userInfo"), dict) else None  # noqa: E501
            )
    except Exception:
        pass

    errors: list[str] = []

    def safe(label: str, key: str, path: dict | None = None, query: dict | None = None) -> object | None:
        try:
            return get_endpoint(bin_path, key, path=path, query=query)
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            return None

    # ── fetch all metrics in one pass ────────────────────────────────────────
    # usersummary.daily: /usersummary-service/usersummary/daily/{display_name}
    #   display_name is auto-filled; calendarDate selects the day
    summary = safe("summary", "usersummary.daily", query={"calendarDate": today})

    # wellness.heart-rate.daily: /wellness-service/wellness/dailyHeartRate/{display_name}
    #   display_name auto-filled; restingHeartRate lives in top-level response
    heart_rates = safe("heart_rates", "wellness.heart-rate.daily", query={"date": today})
    # Fallback: daily summary usually also carries restingHeartRate
    if heart_rates is None and isinstance(summary, dict) and "restingHeartRate" in summary:
        heart_rates = summary

    # sleep.daily: /sleep-service/sleep/dailySleepData  (no path params)
    sleep = safe("sleep", "sleep.daily", query={"date": today})

    # wellness.stress.daily: /wellness-service/wellness/dailyStress/{date}  (date is path param)
    stress = safe("stress", "wellness.stress.daily", path={"date": today})

    # wellness.body-battery.daily: /wellness-service/wellness/bodyBattery/reports/daily
    bb_raw = safe("body_battery", "wellness.body-battery.daily",
                  query={"startDate": today, "endDate": today})
    body_battery = extract_body_battery_list(bb_raw) if bb_raw is not None else None

    # Bail if nothing useful came back
    if summary is None and heart_rates is None and sleep is None:
        emit({
            "ok": False,
            "error": "all_fetches_failed",
            "message": "; ".join(errors) if errors else "All endpoints failed",
        })
        sys.exit(5)

    result: dict = {
        "ok": True,
        "date": today,
        "displayName": display_name,
        "summary": summary or {},
        "heartRates": heart_rates or {},
        "sleep": sleep,
        "stress": stress,
        "bodyBattery": body_battery,
    }
    if errors:
        result["_errors"] = errors

    emit(result)


if __name__ == "__main__":
    main()
