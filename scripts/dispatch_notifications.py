"""Automate the advance-warning notification queue (SMS / WhatsApp).

Dry-run BY DEFAULT: with no flags this rehearses — it builds the real plan
from `/warnings/advance` data, logs every message it *would* send, and sends
nothing. That rehearsal is safe to cron.

    python -m scripts.dispatch_notifications                 # rehearse (default)
    python -m scripts.dispatch_notifications --audience municipal --channel whatsapp
    python -m scripts.dispatch_notifications --rehearse-demo  # prove the lock, any weather
    python -m scripts.dispatch_notifications --live          # real send — double-locked

`--live` is refused with a readable reason unless BOTH locks are open
(HS_ALLOW_LIVE_SEND=1 AND Twilio credentials in the environment/.env), and it
is refused outright for any demo or synthetic-fallback row — exercises must
never message real people. Credentials live only in the gitignored .env; this
script never prints or stores them.

`--rehearse-demo` exists so the refusal can be checked on purpose: it plans a
synthetic demo scenario (every preview labelled as such, so it can never be sent
live) instead of the weather, which means the safety lock is testable on a calm
day. Before it existed, the test for that lock asserted against the real
forecast, so it passed where the data degraded to synthetic rows and failed
where the forecast was mild.
"""
from __future__ import annotations

import argparse
import json
import sys

from core.demo import notifications_payload as demo_notifications_payload
from core.demo import scenario_ids as DEMO_SCENARIOS
from core.notify import AUDIENCES, dispatch_previews, plan_notifications
from core.warnings import advance_warning_payload

# Resolved once, at import: the scenario list is static data, and calling it in
# the argparse choices would be both slower and less readable.
DEMO_SCENARIO_IDS: tuple[str, ...] = DEMO_SCENARIOS()


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
    parser.add_argument(
        "--rehearse-demo", metavar="SCENARIO", nargs="?", const="", choices=["", *DEMO_SCENARIO_IDS],
        help="plan against a synthetic demo scenario instead of the weather. The refusal that "
             "protects real people is then exercised in any weather, not only when the forecast "
             "happens to cross the notification bar — which is how a rehearsal of the safety lock "
             "came to pass on a laptop with no internet and fail on CI, where the real forecast "
             "was mild. With no scenario named, the first one that actually plans a message is "
             "used (a mild scenario plans none, which would rehearse nothing).",
    )
    return parser


def _rehearsal_plan(scenario: str) -> tuple[str, dict]:
    """The demo plan to rehearse: the named one, or the first that plans a message.

    An explicitly named mild scenario is honoured even if it has nothing to say —
    that is a legitimate answer — but the bare flag is not allowed to rehearse
    silence, because a rehearsal of nothing proves nothing about the lock.
    """
    if scenario:
        return scenario, demo_notifications_payload(scenario)

    first: tuple[str, dict] | None = None
    for candidate in DEMO_SCENARIO_IDS:
        plan = demo_notifications_payload(candidate)
        if first is None:
            first = (candidate, plan)
        if plan["previews"]:
            return candidate, plan
    return first  # every scenario is quiet; say so rather than inventing one


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    scenario_note: str | None = None

    if args.rehearse_demo is not None:
        # Every preview from here carries is_demo/data_quality_state, so a live
        # run cannot get past the guard below whatever the weather is doing.
        scenario, plan = _rehearsal_plan(args.rehearse_demo)
        previews = plan["previews"]
        quality_state = "demo-synthetic"
        scenario_note = scenario
    else:
        payload = advance_warning_payload(days=args.days)
        plan = plan_notifications(payload["data"], is_demo=False)
        previews = plan["previews"]
        quality_state = payload.get("quality_state")
    if args.audience != "all":
        previews = [p for p in previews if p["audience"] == args.audience]
    if args.channel != "all":
        previews = [p for p in previews if p["channel"] == args.channel]

    if not previews:
        summary = {"dispatched": 0, "dry_run": not args.live,
                   "reason": "no alert in the current window meets the notification bar — silence is the honest output"}
        if scenario_note:
            summary["rehearsed_scenario"] = scenario_note
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

    result["quality_state"] = quality_state
    if scenario_note:
        result["rehearsed_scenario"] = scenario_note
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
