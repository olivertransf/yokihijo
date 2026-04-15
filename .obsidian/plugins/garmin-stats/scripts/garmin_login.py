#!/usr/bin/env python3
"""One-shot Garmin Connect login: saves Garth tokens to ~/.garminconnect (or GARMINTOKENS).

Run in Terminal (interactive). Optional env: EMAIL, PASSWORD, GARMINTOKENS.

  /path/to/.venv/bin/python3 garmin_login.py

Requires: pip install garminconnect (same venv as the Obsidian helper).
"""

from __future__ import annotations

import os
import sys
import traceback
from getpass import getpass
from pathlib import Path

from garth.exc import GarthException, GarthHTTPError

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)


def _is_rate_limited(exc: BaseException) -> bool:
    if isinstance(exc, GarminConnectTooManyRequestsError):
        return True
    text = str(exc).lower()
    return "429" in text or "too many requests" in text


def _print_rate_limit_help() -> None:
    print(
        """
Garmin SSO returned HTTP 429 (Too Many Requests). This is Garmin throttling logins — not a wrong password.

What to do:
  • Stop retrying for a while. Repeated attempts reset the cooldown (often 30–60+ minutes; sometimes longer).
  • Log in once in a normal browser at https://connect.garmin.com/ to confirm the account is fine.
  • Avoid VPN / corporate proxy if you can; try another network if 429 persists.
  • Run this script again after a long pause — one attempt only.

See also: python-garminconnect issues when Garmin changes SSO or tightens limits.
""".strip(),
        file=sys.stderr,
    )


def tokenstore_path() -> Path:
    raw = os.environ.get("GARMINTOKENS", "~/.garminconnect")
    return Path(raw).expanduser().resolve()


def load_or_prompt_creds() -> tuple[str, str]:
    email = (os.environ.get("EMAIL") or "").strip()
    password = (os.environ.get("PASSWORD") or "").strip()
    if not email:
        email = input("Garmin email: ").strip()
    if not password:
        password = getpass("Garmin password: ")
    if not email or not password:
        print("Email and password are required.", file=sys.stderr)
        sys.exit(1)
    return email, password


def try_token_only(store: Path) -> Garmin | None:
    if not store.exists():
        return None
    try:
        g = Garmin()
        g.login(tokenstore=str(store))
        return g
    except FileNotFoundError:
        return None
    except (
        GarminConnectAuthenticationError,
        GarminConnectConnectionError,
        GarthHTTPError,
    ) as e:
        print(f"Stored tokens invalid or expired: {e}", file=sys.stderr)
        print("Will try email/password login…", file=sys.stderr)
        return None


def login_with_password(store: Path) -> Garmin:
    email, password = load_or_prompt_creds()
    while True:
        try:
            garmin = Garmin(
                email=email,
                password=password,
                is_cn=False,
                return_on_mfa=True,
            )
            r1, r2 = garmin.login()

            if r1 == "needs_mfa":
                code = input("Garmin MFA code (from authenticator / SMS): ").strip()
                try:
                    garmin.resume_login(r2, code)
                except GarthHTTPError as e:
                    print(f"MFA failed: {e}", file=sys.stderr)
                    raise
                except GarthException as e:
                    print(f"MFA error: {e}", file=sys.stderr)
                    continue

            store.mkdir(parents=True, exist_ok=True)
            garmin.garth.dump(str(store))
            return garmin

        except GarminConnectTooManyRequestsError as e:
            print(f"{e}", file=sys.stderr)
            _print_rate_limit_help()
            sys.exit(3)
        except GarminConnectAuthenticationError as e:
            print(f"Login failed: {e}", file=sys.stderr)
            retry = input("Try again with different password? [y/N]: ").strip().lower()
            if retry != "y":
                sys.exit(2)
            password = getpass("Garmin password: ")
        except (GarthHTTPError, GarminConnectConnectionError) as e:
            if _is_rate_limited(e):
                print(f"{e}", file=sys.stderr)
                _print_rate_limit_help()
                sys.exit(3)
            print(f"Connection error: {e}", file=sys.stderr)
            traceback.print_exc()
            sys.exit(4)


def main() -> None:
    store = tokenstore_path()
    print(f"Token directory: {store}")

    g = try_token_only(store)
    if g is None:
        print("No valid session on disk — password login required.")
        g = login_with_password(store)
    else:
        print("Already logged in using saved tokens.")

    name = getattr(g, "display_name", None) or "?"
    print(f"OK — signed in as {name}")
    print(f"Tokens saved under: {store}")
    for p in sorted(store.glob("*.json")):
        print(f"  {p.name}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        sys.exit(130)
