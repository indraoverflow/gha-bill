"""Static estimation: read workflow files, expand matrices, estimate cost per run."""

from __future__ import annotations

import itertools
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

from .pricing import Rate, rate_for

EXPR = re.compile(r"\$\{\{.*?\}\}", re.S)

# Default assumed run counts per month when a trigger type carries no schedule.
TRIGGER_RUNS = {
    "push": 60,
    "pull_request": 20,
    "pull_request_target": 20,
    "merge_group": 20,
    "schedule": 0,  # computed from the cron expression
    "workflow_dispatch": 1,
    "workflow_call": 0,
    "release": 1,
}

CRON_RANGE = re.compile(r"^(\*|(\d+)(?:-(\d+))?)(?:/(\d+))?$")


@dataclass
class JobEstimate:
    name: str
    runs_on: str
    combos: int
    minutes_per_combo: float
    rate: Rate
    approximated: List[str] = field(default_factory=list)

    @property
    def billed_minutes(self) -> float:
        return math.ceil(self.minutes_per_combo) * self.combos * self.rate.minute_multiplier

    @property
    def usd(self) -> float:
        return math.ceil(self.minutes_per_combo) * self.combos * self.rate.usd_per_min


@dataclass
class WorkflowEstimate:
    path: str
    name: str
    triggers: List[str]
    runs_per_month: float
    jobs: List[JobEstimate]
    approximated: List[str] = field(default_factory=list)

    @property
    def usd_per_run(self) -> float:
        return sum(j.usd for j in self.jobs)

    @property
    def usd_per_month(self) -> float:
        return self.usd_per_run * self.runs_per_month

    @property
    def billed_minutes_per_month(self) -> float:
        return sum(j.billed_minutes for j in self.jobs) * self.runs_per_month


def workflow_files(root: Path) -> List[Path]:
    base = Path(root) / ".github" / "workflows"
    if not base.is_dir():
        return []
    files = [p for p in sorted(base.iterdir()) if p.suffix in (".yml", ".yaml") and p.is_file()]
    return files


def _triggers(doc: Dict[str, Any]) -> List[str]:
    # YAML 1.1 turns the bare key `on` into True; PyYAML keeps it that way.
    raw = doc.get("on", doc.get(True))
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if isinstance(raw, dict):
        return [str(k) for k in raw]
    return []


def _trigger_config(doc: Dict[str, Any], name: str) -> Any:
    raw = doc.get("on", doc.get(True))
    if isinstance(raw, dict):
        return raw.get(name)
    return None


def _matrix_combos(matrix: Any) -> Tuple[int, List[str]]:
    """Expand a job matrix into a combination count, best effort."""
    notes: List[str] = []
    if not isinstance(matrix, dict):
        return 1, notes
    if "matrix" in matrix:  # `${{ fromJSON(...) }}` style include-only matrices
        matrix = matrix.get("matrix") or {}

    lists: Dict[str, List[Any]] = {}
    for key, value in matrix.items():
        if key in ("include", "exclude"):
            continue
        if isinstance(value, list) and value and not any(isinstance(v, str) and EXPR.search(v) for v in value):
            lists[key] = value
        else:
            notes.append(f"matrix.{key} is dynamic; counted as 1")

    total = 1
    for values in lists.values():
        total *= len(values)

    include = matrix.get("include") or []
    exclude = matrix.get("exclude") or []
    if isinstance(include, list):
        for entry in include:
            if not isinstance(entry, dict):
                continue
            if not any(all(candidate.get(k) == v for k, v in entry.items()) for candidate in _expand(lists)):
                total += 1
    if isinstance(exclude, list) and exclude and not notes:
        total = max(total - len(exclude), 1)
    return max(total, 1), notes


def _expand(lists: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
    if not lists:
        return [{}]
    keys = list(lists)
    return [dict(zip(keys, values)) for values in itertools.product(*(lists[k] for k in keys))]


def estimate_workflow(path: Path, root: Path, default_job_minutes: float = 5.0,
                      prices: Optional[Dict[str, float]] = None,
                      runs_override: Optional[float] = None) -> Optional[WorkflowEstimate]:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError) as exc:  # pragma: no cover - defensive
        raise ValueError(f"{path}: {exc}") from exc
    if not isinstance(doc, dict):
        return None

    triggers = _triggers(doc)
    approximated: List[str] = []
    jobs_out: List[JobEstimate] = []

    for name, job in (doc.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        runs_on = job.get("runs-on", "ubuntu-latest")
        if isinstance(runs_on, list):
            runs_on = runs_on[0] if runs_on else "ubuntu-latest"
        if isinstance(runs_on, str) and EXPR.search(runs_on):
            approximated.append(f"{name}: runs-on is an expression; priced as ubuntu")
            runs_on = "ubuntu-latest"
        rate = rate_for(str(runs_on), prices)
        combos, notes = _matrix_combos(job.get("strategy") or {})
        approximated.extend(f"{name}: {note}" for note in notes)
        if rate.approx:
            approximated.append(f"{name}: {runs_on} given a non-2-core label; price scaled linearly")

        minutes = default_job_minutes
        timeout = job.get("timeout-minutes")
        if isinstance(timeout, (int, float)) and timeout > 0:
            minutes = min(float(timeout), default_job_minutes) if default_job_minutes else float(timeout)
        steps = job.get("steps") or []
        if not steps:
            # reusable-workflow call: `uses:` at job level, minutes unknowable
            approximated.append(f"{name}: reusable workflow call; minutes not estimated")
        jobs_out.append(
            JobEstimate(
                name=str(name),
                runs_on=str(runs_on),
                combos=combos,
                minutes_per_combo=float(minutes),
                rate=rate,
            )
        )

    if runs_override is None:
        runs = runs_per_month(doc, triggers)
    else:
        runs = float(runs_override)
    return WorkflowEstimate(
        path=str(path.relative_to(root)),
        name=str(doc.get("name") or path.stem),
        triggers=triggers,
        runs_per_month=runs,
        jobs=jobs_out,
        approximated=approximated,
    )


def scan(root: Path, default_job_minutes: float = 5.0,
         prices: Optional[Dict[str, float]] = None,
         runs_overrides: Optional[Dict[str, float]] = None) -> List[WorkflowEstimate]:
    root = Path(root)
    overrides = {k.lower(): v for k, v in (runs_overrides or {}).items()}
    out: List[WorkflowEstimate] = []
    for path in workflow_files(root):
        override = overrides.get(path.stem.lower()) or overrides.get(path.name.lower())
        est = estimate_workflow(path, root, default_job_minutes, prices, override)
        if est is not None:
            out.append(est)
    return out


def runs_per_month(doc: Dict[str, Any], triggers: Iterable[str]) -> float:
    """Estimate how often a workflow runs per month from its triggers."""
    total = 0.0
    for trigger in triggers:
        if trigger == "schedule":
            for entry in _as_list(_trigger_config(doc, "schedule")):
                cron = entry.get("cron") if isinstance(entry, dict) else None
                if cron:
                    total += cron_occurrences_per_month(str(cron))
        else:
            total += TRIGGER_RUNS.get(trigger, 1)
    return total or 1.0


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _field_values(field: str, low: int, high: int) -> List[int]:
    values: List[int] = []
    for part in str(field).split(","):
        part = part.strip()
        if not part:
            continue
        match = CRON_RANGE.match(part)
        if not match:
            continue
        base, start, end, step = match.groups()
        step_n = int(step) if step else 1
        if base == "*":
            lo, hi = low, high
        elif end:
            lo, hi = int(start), int(end)
        else:
            lo = hi = int(start)
        values.extend(range(lo, hi + 1, step_n))
    return sorted({v for v in values if low <= v <= high}) or [low]


def cron_occurrences_per_month(expression: str) -> float:
    """Count cron matches over the next 365 days, then normalise to a month."""
    fields = str(expression).split()
    if len(fields) != 5:
        return 1.0
    minutes = _field_values(fields[0], 0, 59)
    hours = _field_values(fields[1], 0, 23)
    doms = _field_values(fields[2], 1, 31)
    months = _field_values(fields[3], 1, 12)
    dows = _field_values(fields[4], 0, 6)

    times_per_day = len(minutes) * len(hours)
    dom_restricted = fields[2].strip() != "*"
    dow_restricted = fields[4].strip() != "*"

    now = datetime.now(timezone.utc)
    days = 0
    for offset in range(365):
        day = now + timedelta(days=offset)
        if day.month not in months:
            continue
        dom_hit = day.day in doms
        dow_hit = (day.weekday() + 1) % 7 in dows  # cron: 0=Sunday
        if dom_restricted and dow_restricted:
            hit = dom_hit or dow_hit
        elif dom_restricted:
            hit = dom_hit
        elif dow_restricted:
            hit = dow_hit
        else:
            hit = True
        if hit:
            days += 1
    return round(days * times_per_day / 12.0, 2)
