"""Tests for the estimate engine, billing rules and CLI contract."""

from __future__ import annotations

import json

from gha_bill.cli import main
from gha_bill.pricing import billable_minutes, quota_usage, rate_for
from gha_bill.workflows import cron_occurrences_per_month, scan


def _workflow(repo, name, text):
    path = repo / ".github" / "workflows" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


MATRIX_WORKFLOW = """
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 4
    strategy:
      matrix:
        python: ["3.10", "3.11", "3.12"]
        os: [ubuntu-latest]
    steps:
      - run: pytest
  mac:
    runs-on: macos-14
    steps:
      - run: echo hi
"""


def test_windows_rate_is_double_linux():
    assert rate_for("windows-latest").usd_per_min == 2 * rate_for("ubuntu-latest").usd_per_min


def test_macos_rate_is_ten_times_linux():
    assert rate_for("macos-14").usd_per_min == 10 * rate_for("ubuntu-latest").usd_per_min


def test_larger_runner_is_scaled_and_flagged():
    rate = rate_for("ubuntu-latest-8-cores")
    assert rate.approx is True
    assert rate.usd_per_min == rate_for("ubuntu-latest").usd_per_min * 4


def test_custom_price_override():
    assert rate_for("ubuntu-latest", {"linux": 0.01}).usd_per_min == 0.01


def test_billable_minutes_round_up_per_job_not_per_total():
    linux = rate_for("ubuntu-latest")
    # 61s + 61s must be 2 + 2 minutes, not ceil(122/60) = 3
    assert billable_minutes([61, 61], linux) == 4


def test_quota_overage():
    assert quota_usage(2500, "free")["overage_minutes"] == 500
    assert quota_usage(100, "free")["overage_minutes"] == 0


def test_cron_daily_is_about_thirty_a_month():
    assert 28 <= cron_occurrences_per_month("0 2 * * *") <= 32


def test_cron_every_fifteen_minutes():
    assert 2800 <= cron_occurrences_per_month("*/15 * * * *") <= 3000


def test_matrix_expansion_multiplies_jobs(tmp_path):
    _workflow(tmp_path, "ci.yml", MATRIX_WORKFLOW)
    estimates = scan(tmp_path, default_job_minutes=4)
    assert len(estimates) == 1
    jobs = {job.name: job for job in estimates[0].jobs}
    assert jobs["test"].combos == 3
    # 3 combos x 4 min x $0.008 plus one 4-minute macOS job at $0.08
    assert round(estimates[0].usd_per_run, 4) == round(3 * 4 * 0.008 + 4 * 0.08, 4)


def test_timeout_minutes_caps_the_default(tmp_path):
    _workflow(tmp_path, "ci.yml", """
name: Slow
on: workflow_dispatch
jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 2
    steps:
      - run: sleep 120
""")
    estimates = scan(tmp_path, default_job_minutes=30)
    assert estimates[0].jobs[0].minutes_per_combo == 2


def test_schedule_runs_per_month_comes_from_cron(tmp_path):
    _workflow(tmp_path, "nightly.yml", """
name: Nightly
on:
  schedule:
    - cron: "0 3 * * *"
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo build
""")
    estimates = scan(tmp_path)
    assert 28 <= estimates[0].runs_per_month <= 32


def test_scan_json_contract(tmp_path, capsys):
    _workflow(tmp_path, "ci.yml", MATRIX_WORKFLOW)
    code = main(["scan", str(tmp_path), "--json", "--plan", "free"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["workflows"][0]["name"] == "CI"
    assert out["usd_per_month"] > 0
    assert out["quota"]["plan"] == "free"


def test_check_fails_over_budget(tmp_path, capsys):
    _workflow(tmp_path, "ci.yml", MATRIX_WORKFLOW)
    assert main(["check", str(tmp_path), "--budget", "0.01"]) == 1
    capsys.readouterr()
    assert main(["check", str(tmp_path), "--budget", "1000"]) == 0


def test_runs_per_month_override(tmp_path):
    _workflow(tmp_path, "ci.yml", MATRIX_WORKFLOW)
    estimates = scan(tmp_path, runs_overrides={"ci": 1})
    assert estimates[0].runs_per_month == 1


def test_no_workflows_is_not_an_error(tmp_path, capsys):
    code = main(["scan", str(tmp_path)])
    assert code == 0
    assert "No workflow files" in capsys.readouterr().out
