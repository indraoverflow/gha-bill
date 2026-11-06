"""Runner price table and billing rules for GitHub-hosted runners."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Dict, Iterable, Optional

# USD per billable minute, GitHub-hosted standard runners.
# GitHub already folds the OS multiplier into these rates (Windows = 2x Linux,
# macOS = 10x Linux), so cost is: billed_minutes * usd_per_min.
# Source: GitHub Actions billing docs. Override with --prices <file.json>.
PRICES_UPDATED = "2025-01"
BASE_PRICES: Dict[str, float] = {
    "linux": 0.008,
    "windows": 0.016,
    "macos": 0.080,
}

# Billed-minute multipliers used for free-quota accounting only.
MINUTE_MULTIPLIER: Dict[str, float] = {
    "linux": 1.0,
    "windows": 2.0,
    "macos": 10.0,
}

# Included minutes per plan (Linux-equivalent, private repos, standard runners).
INCLUDED_MINUTES: Dict[str, Optional[int]] = {
    "none": None,
    "free": 2000,
    "pro": 3000,
    "team": 10000,
    "enterprise": 50000,
}


def os_class(runs_on: str) -> str:
    """Map a `runs-on` label to a price class."""
    label = (runs_on or "").lower()
    if label.startswith(("ubuntu", "linux")):
        return "linux"
    if label.startswith("windows"):
        return "windows"
    if label.startswith(("macos", "mac")):
        return "macos"
    return "linux"


CORE_LABEL = re.compile(r"(\d{1,3})[-_]?cores?\b", re.I)


def core_count(runs_on: str) -> int:
    """Best-effort core count for larger-runner labels (`ubuntu-4-core`, `ubuntu-latest-8-cores`).

    Only a `-N-core(s)` token counts: plain numbers in a label (`macos-14`) are
    OS versions, not cores.
    """
    match = CORE_LABEL.search(runs_on or "")
    if not match:
        return 2
    cores = int(match.group(1))
    return cores if 1 <= cores <= 128 else 2


@dataclass(frozen=True)
class Rate:
    os: str
    usd_per_min: float
    minute_multiplier: float
    approx: bool = False


def rate_for(runs_on: str, prices: Optional[Dict[str, float]] = None) -> Rate:
    """Return the billing rate for a runner label.

    Labels carrying a core count other than 2 (larger runners) are priced
    linearly off the 2-core rate and flagged `approx`, because GitHub prices
    larger runners per core-hour with storage billed separately.
    """
    table = dict(BASE_PRICES)
    if prices:
        table.update({k.lower(): float(v) for k, v in prices.items()})
    cls = os_class(runs_on)
    base = table[cls]
    cores = core_count(runs_on)
    approx = False
    if cores != 2:
        base = base * (cores / 2.0)
        approx = True
    return Rate(
        os=cls,
        usd_per_min=round(base, 6),
        minute_multiplier=MINUTE_MULTIPLIER[cls],
        approx=approx,
    )


def billable_minutes(seconds: Iterable[float], rate: Rate) -> float:
    """GitHub rounds every job's duration up to the whole minute, then applies the OS multiplier."""
    total = 0.0
    for value in seconds:
        total += math.ceil(max(float(value), 0.0) / 60.0) * rate.minute_multiplier
    return total


def quota_usage(billed_minutes: float, plan: str) -> Dict[str, Optional[float]]:
    """Compare billed minutes against the plan's included Linux-equivalent minutes."""
    included = INCLUDED_MINUTES.get((plan or "none").lower())
    if included is None:
        return {"plan": plan, "included_minutes": None, "overage_minutes": None}
    return {
        "plan": plan,
        "included_minutes": included,
        "overage_minutes": round(max(billed_minutes - included, 0.0), 1),
    }
