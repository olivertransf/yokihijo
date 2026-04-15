#!/usr/bin/env python3
"""JSON snapshot for Obsidian claude-usage (claude-monitor semantics, no Keychain).

Reads ~/.claude/projects JSONL via claude_monitor.analyze_usage and mirrors the
active 5h session metrics shown in `cmonitor` realtime view:
  - Bar 1: session token usage vs plan token limit
  - Bar 2: elapsed / total time within the session window
Requires: pip install claude-monitor
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

import pytz


def _payload(
    *,
    five_util: float,
    seven_util: float,
    resets_at: Optional[str],
    meta: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "five_hour": {
            "utilization": round(five_util, 1),
            "resets_at": resets_at,
        },
        "seven_day": {
            "utilization": round(seven_util, 1),
            "resets_at": resets_at,
        },
        "_meta": meta,
    }


def main() -> None:
    from claude_monitor.data.analysis import analyze_usage
    from claude_monitor.core.plans import get_token_limit
    from claude_monitor.ui.display_controller import SessionCalculator
    from claude_monitor.utils.time_utils import percentage

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--plan",
        default="custom",
        choices=["pro", "max5", "max20", "custom"],
    )
    ap.add_argument(
        "--custom-limit-tokens",
        type=int,
        default=None,
        help="Override token limit when set (any plan)",
    )
    ap.add_argument(
        "--data-path",
        default="",
        help="Claude projects directory (default: ~/.claude/projects)",
    )
    ap.add_argument("--hours-back", type=int, default=192)
    args = ap.parse_args()

    data_path = args.data_path.strip() or None
    data = analyze_usage(
        hours_back=args.hours_back,
        use_cache=False,
        quick_start=False,
        data_path=data_path,
    )
    blocks: List[Dict[str, Any]] = data.get("blocks") or []

    current_time = datetime.now(pytz.UTC)
    active = next(
        (b for b in blocks if isinstance(b, dict) and b.get("isActive")),
        None,
    )

    if not active:
        print(
            json.dumps(
                _payload(
                    five_util=0.0,
                    seven_util=0.0,
                    resets_at=None,
                    meta={
                        "source": "cmonitor",
                        "active": False,
                        "note": "No active session — start Claude Code in this account.",
                        "bar_labels": ["Session tokens", "Session window"],
                    },
                )
            )
        )
        return

    token_limit = int(get_token_limit(args.plan, blocks))
    if args.custom_limit_tokens is not None and args.custom_limit_tokens > 0:
        token_limit = args.custom_limit_tokens

    tokens_used = int(active.get("totalTokens") or 0)
    usage_pct = (
        float(percentage(tokens_used, token_limit)) if token_limit > 0 else 0.0
    )

    session_for_time = {
        "start_time_str": active.get("startTime"),
        "end_time_str": active.get("endTime"),
    }
    calc = SessionCalculator()
    time_data = calc.calculate_time_data(session_for_time, current_time)
    total_m = max(0.001, float(time_data["total_session_minutes"]))
    elapsed_m = max(0.0, float(time_data["elapsed_session_minutes"]))
    time_pct = min(100.0, float(percentage(elapsed_m, total_m)))

    reset_iso = time_data["reset_time"].isoformat()

    print(
        json.dumps(
            _payload(
                five_util=usage_pct,
                seven_util=time_pct,
                resets_at=reset_iso,
                meta={
                    "source": "cmonitor",
                    "active": True,
                    "plan": args.plan,
                    "tokens_used": tokens_used,
                    "token_limit": token_limit,
                    "bar_labels": ["Session tokens", "Session window"],
                },
            )
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"error": str(e), "error_type": type(e).__name__}))
        sys.exit(1)
