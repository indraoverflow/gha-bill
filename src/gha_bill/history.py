"""Actual spend from the GitHub API: real job durations, no guesswork."""

from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .pricing import rate_for

API = "https://api.github.com"


class HistoryError(RuntimeError):
    pass


def token() -> Optional[str]:
    env = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if env:
        return env.strip()
    path = Path.home() / ".github_token"
    if path.is_file():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    return None


def _get(url: str, tok: Optional[str]) -> Any:
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "gha-bill",
        **({"Authorization": f"Bearer {tok}"} if tok else {}),
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise HistoryError(f"{exc.code} {exc.reason} for {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise HistoryError(f"network error for {url}: {exc.reason}") from exc


@dataclass
class WorkflowHistory:
    name: str
    runs: int
    billed_minutes: float
    usd: float
    window_days: float

    @property
    def usd_per_month(self) -> float:
        return self.usd / self.window_days * 30.0 if self.window_days else 0.0


def actual_spend(repo: str, limit: int = 20, tok: Optional[str] = None) -> Dict[str, Any]:
    """Sum real per-job durations for the last `limit` runs of every workflow."""
    tok = tok or token()
    runs = _get(f"{API}/repos/{repo}/actions/runs?per_page={max(limit, 1)}", tok).get("workflow_runs", [])
    if not runs:
        raise HistoryError(f"no workflow runs returned for {repo}")

    per_workflow: Dict[str, WorkflowHistory] = {}
    first: Optional[datetime] = None
    last: Optional[datetime] = None
    seen = 0

    for run in runs[:limit]:
        started = _parse(run.get("run_started_at") or run.get("created_at"))
        if started:
            first = started if first is None or started < first else first
            last = started if last is None or started > last else last
        jobs = _get(f"{API}/repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100", tok).get("jobs", [])
        name = (run.get("name") or run.get("path") or "workflow").strip()
        bucket = per_workflow.setdefault(
            name, WorkflowHistory(name=name, runs=0, billed_minutes=0.0, usd=0.0, window_days=0.0)
        )
        bucket.runs += 1
        seen += 1
        for job in jobs:
            if job.get("conclusion") in ("skipped",):
                continue
            labels = job.get("labels") or ["ubuntu-latest"]
            rate = rate_for(labels[0])
            seconds = _duration(job)
            if seconds is None:
                continue
            billed = math.ceil(seconds / 60.0) * rate.minute_multiplier
            bucket.billed_minutes += billed
            bucket.usd += math.ceil(seconds / 60.0) * rate.usd_per_min

    window = max(((last - first).days if first and last else 0) + 1, 1)
    rows: List[WorkflowHistory] = []
    for bucket in per_workflow.values():
        bucket.window_days = float(window)
        rows.append(bucket)
    rows.sort(key=lambda r: r.usd, reverse=True)
    return {
        "repo": repo,
        "runs_sampled": seen,
        "window_days": window,
        "workflows": rows,
        "usd_sampled": round(sum(r.usd for r in rows), 2),
        "billed_minutes_sampled": round(sum(r.billed_minutes for r in rows), 1),
    }


def _duration(job: Dict[str, Any]) -> Optional[float]:
    start = _parse(job.get("started_at"))
    end = _parse(job.get("completed_at"))
    if not start or not end:
        return None
    return max((end - start).total_seconds(), 0.0)


def _parse(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None
