#!/usr/bin/env python3
"""
Soundfolio JSON bridge for the Obsidian plugin.
Outputs a single JSON line to stdout.
Usage: python3 soundfolio_json.py [--range 30d|3m|6m|1y|all] [--granularity weeks|months|days]
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent.parent / ".env"


def range_to_since(r):
    now = datetime.now(timezone.utc)
    if r == "30d": return now - timedelta(days=30)
    if r == "3m":  return now - timedelta(days=91)
    if r == "6m":  return now - timedelta(days=182)
    if r == "1y":  return now - timedelta(days=365)
    return None


def week_key(dt):
    """ISO week start (Monday)."""
    monday = dt - timedelta(days=dt.weekday())
    return monday.strftime("%Y-%m-%d")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--range", default="30d",
                        choices=["30d", "3m", "6m", "1y", "all"])
    parser.add_argument("--granularity", default="weeks",
                        choices=["weeks", "months", "days"])
    parser.add_argument("--env", default=None,
                        help="Explicit path to .env file")
    args = parser.parse_args()

    # Resolve .env: explicit arg > next to script's grandparent > hardcoded fallback
    env_candidates = [
        Path(args.env) if args.env else None,
        Path(__file__).parent.parent / ".env",
        Path("/Users/olivertran/Documents/Projects/SpotifyStats/.env"),
    ]
    for candidate in env_candidates:
        if candidate and candidate.exists():
            load_dotenv(candidate)
            break

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print(json.dumps({"ok": False, "error": "DATABASE_URL not found in .env"}))
        sys.exit(0)

    since = range_to_since(args.range)
    date_filter = 'AND "playedAt" >= %s' if since else ""
    params_base = [since] if since else []

    try:
        conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor)
        conn.autocommit = True
        cur = conn.cursor()

        # Totals
        cur.execute(
            f'SELECT COUNT(*) AS streams, COALESCE(SUM("durationMs"),0) AS total_ms '
            f'FROM "Stream" WHERE "isDemo" = false {date_filter}',
            params_base,
        )
        totals_row = cur.fetchone()
        total_streams = int(totals_row["streams"])
        total_ms = int(totals_row["total_ms"])

        # Unique
        cur.execute(
            f'SELECT COUNT(DISTINCT "trackId") AS tracks, COUNT(DISTINCT "artistName") AS artists '
            f'FROM "Stream" WHERE "isDemo" = false {date_filter}',
            params_base,
        )
        uniq = cur.fetchone()

        # Span
        cur.execute(
            'SELECT MIN("playedAt") AS first, MAX("playedAt") AS last '
            'FROM "Stream" WHERE "isDemo" = false'
        )
        span_row = cur.fetchone()

        # Days in period for avg calculations
        if since:
            days_in_period = max(1, (datetime.now(timezone.utc) - since).days)
        elif span_row and span_row["first"] and span_row["last"]:
            days_in_period = max(1, (span_row["last"] - span_row["first"]).days + 1)
        else:
            days_in_period = 1

        # Top artists
        cur.execute(
            f"""SELECT "artistName", "artistArt", COUNT(*) AS streams,
                       COALESCE(SUM("durationMs"),0)/60000 AS minutes
                FROM "Stream" WHERE "isDemo" = false {date_filter}
                GROUP BY "artistName", "artistArt"
                ORDER BY streams DESC LIMIT 10""",
            params_base,
        )
        artists_raw = cur.fetchall()
        # Dedupe by name (keep highest streams), filter out placeholder art
        PLACEHOLDER = "2a96cbd8b46e442fc41c2b86b821562f"
        seen_artists = {}
        for a in artists_raw:
            name = a["artistName"]
            if name not in seen_artists:
                seen_artists[name] = a
        artists = []
        for name, a in list(seen_artists.items())[:10]:
            art = a["artistArt"]
            if art and PLACEHOLDER in art:
                art = None
            artists.append({"name": name, "art": art, "streams": int(a["streams"]), "minutes": int(a["minutes"])})

        # Top tracks
        cur.execute(
            f"""SELECT "trackId", "trackName", "artistName", "albumName", "albumArt",
                       COUNT(*) AS streams,
                       COALESCE(SUM("durationMs"),0)/60000 AS minutes
                FROM "Stream" WHERE "isDemo" = false {date_filter}
                GROUP BY "trackId","trackName","artistName","albumName","albumArt"
                ORDER BY streams DESC LIMIT 10""",
            params_base,
        )
        tracks = [
            {
                "id": t["trackId"],
                "name": t["trackName"],
                "artist": t["artistName"],
                "album": t["albumName"],
                "art": t["albumArt"],
                "streams": int(t["streams"]),
                "minutes": int(t["minutes"]),
            }
            for t in cur.fetchall()
        ]

        # Recent plays
        cur.execute(
            """SELECT "trackName", "artistName", "albumArt",
                      to_char("playedAt" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS played_at
               FROM "Stream" WHERE "isDemo" = false
               ORDER BY "playedAt" DESC LIMIT 20""",
        )
        recent = [
            {"name": r["trackName"], "artist": r["artistName"],
             "art": r["albumArt"], "playedAt": r["played_at"]}
            for r in cur.fetchall()
        ]

        # Historical chart data
        cur.execute(
            f"""SELECT "playedAt", "durationMs" FROM "Stream"
                WHERE "isDemo" = false {date_filter}
                ORDER BY "playedAt" ASC""",
            params_base,
        )
        all_streams = cur.fetchall()

        history = {}
        gran = args.granularity
        for s in all_streams:
            dt = s["playedAt"]
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if gran == "months":
                key = dt.strftime("%Y-%m")
            elif gran == "days":
                key = dt.strftime("%Y-%m-%d")
            else:
                key = week_key(dt)
            if key not in history:
                history[key] = {"label": key, "streams": 0, "minutes": 0}
            history[key]["streams"] += 1
            history[key]["minutes"] += int(s["durationMs"]) // 60000

        history_list = sorted(history.values(), key=lambda x: x["label"])

        cur.close()
        conn.close()

        result = {
            "ok": True,
            "range": args.range,
            "granularity": gran,
            "totals": {
                "streams": total_streams,
                "minutes": total_ms // 60000,
                "hours": total_ms // 3600000,
            },
            "unique": {
                "tracks": int(uniq["tracks"]),
                "artists": int(uniq["artists"]),
            },
            "avgs": {
                "minutesPerDay": round(total_ms / 60000 / days_in_period),
                "streamsPerDay": round(total_streams / days_in_period),
                "daysInPeriod": days_in_period,
            },
            "artists": artists,
            "tracks": tracks,
            "recent": recent,
            "history": history_list,
            "span": {
                "first": span_row["first"].strftime("%Y-%m-%d") if span_row and span_row["first"] else None,
                "last":  span_row["last"].strftime("%Y-%m-%d")  if span_row and span_row["last"]  else None,
            },
        }

        print(json.dumps(result))

    except Exception as e:
        import traceback
        print(json.dumps({"ok": False, "error": str(e), "trace": traceback.format_exc()}))


if __name__ == "__main__":
    main()
