"""Automate the advance-warning notification queue (SMS / WhatsApp).

Dry-run BY DEFAULT: with no flags this rehearses — it builds the real plan
from `/warnings/advance` data, logs every message it *would* send, and sends
nothing. That rehearsal is safe to cron.

    python -m scripts.dispatch_notifications                 # rehearse (default)
    python -m scripts.dispatch_notifications --audience municipal --channel whatsapp
    python -m scripts.dispatch_notifications --live          # real send — double-locked

`--live` is refused with a readable reason unless BOTH locks are open
(HS_ALLOW_LIVE_SEND=1 AND Twilio credentials in the environment/.env), and it
is refused outright for any demo or synthetic-fallback row — exercises must
never message real people. Credentials live only in the gitignored .env; this
script never prints or stores them.
"""
from __future__ import annotations

import argparse
import json
import sys

from core.notify import AUDIENCES, dispatch_previews, plan_notifications
from core.warnings import advance_warning_payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true",
                        help="actually send (requires HS_ALLOW_LIVE_SEND=1 + Twilio credentials; "
                             "demo/synthetic rows are always refused)")
    parser.add_argument("--days", type=int, default=5, help="forecast window to plan over (default 5)")
    parser.add_argument("--audience", choices=[*AUDIENCES, "all"], default="all",
                        help="restrict to one audience (default all)")
    parser.add_argument("--channel", choices=["sms", "whatsapp", "all"], default="all",
                        help="restrict to one channel (default all)")
    parser.add_argument("--to", action="append", default=None,
                        help="recipient override (repeatable); defaults to ALERT_TO_NUMBERS. "
                             "WhatsApp numbers need the 'whatsapp:' prefix, e.g. whatsapp:+91...")
    parser.add_argument("--json", action="store_true", help="machine-readable summary on stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    payload = advance_warning_payload(days=args.days)
    plan = plan_notifications(payload["data"], is_demo=False)
    previews = plan["previews"]
    if args.audience != "all":
        previews = [p for p in previews if p["audience"] == args.audience]
    if args.channel != "all":
        previews = [p for p in previews if p["channel"] == args.channel]

    if not previews:
        summary = {"dispatched": 0, "dry_run": not args.live,
                   "reason": "no alert in the current window meets the notification bar — silence is the honest output"}
        print(json.dumps(summary) if args.json else summary["reason"])
        return 0

    try:
        result = dispatch_previews(previews, dry_run=not args.live, to_numbers=args.to)
    except PermissionError as exc:
        message = f"REFUSED: {exc}"
        if args.json:
            print(json.dumps({"dispatched": 0, "dry_run": not args.live, "refused": str(exc)}))
        else:
            print(message, file=sys.stderr)
        return 2

    result["quality_state"] = payload.get("quality_state")
    result["planned_previews"] = len(previews)
    if args.json:
        print(json.dumps(result))
    else:
        mode = "LIVE SEND" if not result["dry_run"] else "DRY RUN (nothing sent)" 
        print(f"{mode} · dispatched {result['dispatched']} preview(s) · records {result['records']} · "
              f"statuses {result['status_counts']} · payload quality: {result['quality_state']} · log: {result['log_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
