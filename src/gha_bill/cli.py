"""gha-bill command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

from . import __version__
from .history import HistoryError, actual_spend
from .pricing import PRICES_UPDATED
from .report import as_json, summary, table, verdict, warnings_for
from .workflows import scan

PLANS = ("none", "free", "pro", "team", "enterprise")


def _pairs(values: Optional[List[str]]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for item in values or []:
        if "=" not in item:
            raise SystemExit(f"--runs-per-month expects WORKFLOW=N, got {item!r}")
        key, _, value = item.partition("=")
        out[key.strip()] = float(value)
    return out


def _load_prices(path: Optional[str]) -> Optional[Dict[str, float]]:
    if not path:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("--prices must contain a JSON object of {os: usd_per_minute}")
    return {str(k): float(v) for k, v in data.items()}


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("path", nargs="?", default=".", help="repository path (default: .)")
    parser.add_argument("--default-job-minutes", type=float, default=5.0,
                        help="minutes assumed per job when timeout-minutes is absent (default: 5)")
    parser.add_argument("--prices", help="JSON file overriding USD per minute per OS")
    parser.add_argument("--runs-per-month", action="append", metavar="WORKFLOW=N",
                        help="override the run count for one workflow (repeatable)")
    parser.add_argument("--plan", choices=PLANS, default="none", help="plan used for included minutes")
    parser.add_argument("--public", action="store_true",
                        help="repo is public: standard runners are free but minutes still count")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gha-bill",
        description="Know what your GitHub Actions cost per workflow and per month.",
    )
    parser.add_argument("--version", action="version", version=f"gha-bill {__version__}")
    sub = parser.add_subparsers(dest="command")

    scan_parser = sub.add_parser("scan", help="estimate cost from workflow files (offline)")
    _common(scan_parser)

    check_parser = sub.add_parser("check", help="fail when monthly estimate exceeds a budget")
    _common(check_parser)
    check_parser.add_argument("--budget", type=float, required=True, help="USD per month")

    history_parser = sub.add_parser("history", help="measure real spend from the GitHub API")
    history_parser.add_argument("repo", help="owner/name")
    history_parser.add_argument("--limit", type=int, default=20, help="runs sampled per repo (default: 20)")
    history_parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2

    if args.command == "history":
        try:
            data = actual_spend(args.repo, args.limit)
        except HistoryError as exc:
            print(f"gha-bill: {exc}", file=sys.stderr)
            return 2
        if args.json:
            print(as_json({**data, "workflows": [w.__dict__ for w in data["workflows"]]}))
            return 0
        print(f"{data['repo']}: sampled {data['runs_sampled']} runs over {data['window_days']} days")
        print(f"{'WORKFLOW':38} {'RUNS':>5} {'BILLED MIN':>11} {'US$':>9} {'US$/MO':>9}")
        for row in data["workflows"]:
            print(f"{row.name[:38]:38} {row.runs:>5} {row.billed_minutes:>11,.0f} "
                  f"{row.usd:>9,.2f} {row.usd_per_month:>9,.2f}")
        print(f"{'TOTAL':38} {data['runs_sampled']:>5} {data['billed_minutes_sampled']:>11,.0f} "
              f"{data['usd_sampled']:>9,.2f}")
        return 0

    prices = _load_prices(args.prices)
    overrides = _pairs(args.runs_per_month)
    try:
        estimates = scan(Path(args.path), args.default_job_minutes, prices, overrides)
    except ValueError as exc:
        print(f"gha-bill: {exc}", file=sys.stderr)
        return 2

    payload = summary(estimates, args.plan, args.public)

    if args.command == "check":
        total = payload["usd_per_month"]
        if args.json:
            print(as_json({**payload, "budget": args.budget,
                           "verdict": verdict(total, args.budget)}))
        else:
            print(table(estimates))
            print()
            print(f"Budget: {verdict(total, args.budget)}")
            for note in warnings_for(estimates):
                print(f"  note: {note}")
        return 1 if total > args.budget else 0

    if args.json:
        print(as_json(payload))
        return 0

    print(table(estimates))
    print()
    quota = payload["quota"]
    if args.public:
        print("Public repo: standard GitHub-hosted runners are free; billed minutes shown for quota tracking only.")
    elif quota.get("included_minutes"):
        print(f"Plan {quota['plan']}: {quota['included_minutes']:,} included minutes, "
              f"{quota['overage_minutes']:,.0f} over before any charge.")
    print(f"Prices: GitHub-hosted standard runners, table dated {PRICES_UPDATED} (override with --prices).")
    for note in warnings_for(estimates):
        print(f"  note: {note}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
