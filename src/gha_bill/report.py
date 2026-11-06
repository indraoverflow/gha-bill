"""Rendering: plain-text tables, JSON, and budget verdicts."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .pricing import quota_usage
from .workflows import WorkflowEstimate


def _money(value: float) -> str:
    return f"${value:,.2f}" if value >= 0.01 else f"${value:,.4f}"


def table(estimates: List[WorkflowEstimate]) -> str:
    if not estimates:
        return "No workflow files found under .github/workflows/."
    header = ("WORKFLOW", "TRIGGERS", "JOBS", "RUNS/MO", "MIN/RUN", "US$/RUN", "US$/MO")
    rows: List[tuple] = []
    for est in estimates:
        jobs = len(est.jobs)
        combos = sum(j.combos for j in est.jobs)
        minute = sum(j.billed_minutes for j in est.jobs) / j_denominator(est)
        rows.append((
            est.name[:34],
            ",".join(est.triggers)[:18] or "-",
            f"{jobs} ({combos} jobs)" if combos != jobs else str(jobs),
            f"{est.runs_per_month:,.0f}",
            f"{minute:,.0f}",
            _money(est.usd_per_run),
            _money(est.usd_per_month),
        ))
    total = sum(est.usd_per_month for est in estimates)
    rows.append(("TOTAL", "", "", "", "", "", _money(total)))
    widths = [max(len(str(r[i])) for r in [header] + rows) for i in range(len(header))]
    lines = ["  ".join(str(h).ljust(widths[i]) for i, h in enumerate(header)).rstrip()]
    lines.append("  ".join("-" * widths[i] for i in range(len(header))))
    for index, row in enumerate(rows):
        line = "  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)).rstrip()
        lines.append(line)
        if index == len(rows) - 2:
            lines.append("  ".join("-" * widths[i] for i in range(len(header))))
    return "\n".join(lines)


def j_denominator(est: WorkflowEstimate) -> int:
    return max(len(est.jobs), 1)


def warnings_for(estimates: List[WorkflowEstimate]) -> List[str]:
    out: List[str] = []
    for est in estimates:
        for note in est.approximated:
            out.append(f"{est.name}: {note}")
    return out


def summary(estimates: List[WorkflowEstimate], plan: str = "none",
            public_repo: bool = False) -> Dict[str, Any]:
    usd_per_month = sum(est.usd_per_month for est in estimates)
    minutes = sum(est.billed_minutes_per_month for est in estimates)
    quotas = quota_usage(minutes, plan) if not public_repo else {
        "plan": plan, "included_minutes": None, "overage_minutes": 0.0,
    }
    return {
        "usd_per_month": round(usd_per_month, 2),
        "billed_minutes_per_month": round(minutes, 1),
        "public_repo": public_repo,
        "quota": quotas,
        "workflows": [
            {
                "name": est.name,
                "path": est.path,
                "triggers": est.triggers,
                "runs_per_month": est.runs_per_month,
                "usd_per_run": round(est.usd_per_run, 4),
                "usd_per_month": round(est.usd_per_month, 2),
                "billed_minutes_per_month": round(est.billed_minutes_per_month, 1),
                "jobs": [
                    {
                        "name": job.name,
                        "runs_on": job.runs_on,
                        "combinations": job.combos,
                        "minutes_per_combination": job.minutes_per_combo,
                        "usd_per_run": round(job.usd, 4),
                    }
                    for job in est.jobs
                ],
            }
            for est in estimates
        ],
    }


def as_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=False)


def verdict(usd_per_month: float, budget: Optional[float]) -> str:
    if budget is None:
        return "no budget set"
    if usd_per_month > budget:
        return f"OVER budget: {_money(usd_per_month)} > {_money(budget)}/mo"
    return f"within budget: {_money(usd_per_month)} <= {_money(budget)}/mo"
