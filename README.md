# gha-bill

[![CI](https://github.com/indraoverflow/gha-bill/actions/workflows/ci.yml/badge.svg)](https://github.com/indraoverflow/gha-bill/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Know what your GitHub Actions cost — per workflow, per month — before the invoice arrives.**

One command, no config, no GitHub token:

```console
$ gha-bill scan .
WORKFLOW  TRIGGERS           JOBS        RUNS/MO  MIN/RUN  US$/RUN  US$/MO
--------  -----------------  ----------  -------  -------  -------  ------
CI        push,pull_request  2 (4 jobs)  80       32       $0.52    $41.60
Nightly   schedule           1           30       10       $0.08    $2.43
--------  -----------------  ----------  -------  -------  -------  ------
TOTAL                                                               $44.03
```

Two numbers teams never look at until the bill lands: which workflow is the
expensive one, and what it costs per month. `gha-bill` answers both from the
files already in your repo.

## Why

GitHub Actions billing hides three multipliers, and they compound:

1. **Per-job minute rounding.** Every job is rounded *up* to the whole minute.
   Ten 40-second jobs bill 10 minutes, not 6.7.
2. **OS multipliers.** Windows bills 2× Linux minutes, macOS 10×.
3. **Matrix expansion.** A 3×2 matrix is six billed jobs per run, times every
   push and PR, times every month.

A repo with one innocent `macos-latest` job is often the most expensive thing
in its CI. `gha-bill` makes that visible before you merge the workflow.

## Install

```console
pipx install gha-bill          # or: uv tool install gha-bill
# from source
git clone https://github.com/indraoverflow/gha-bill && cd gha-bill && pip install -e .
```

Requires Python 3.10+ (CI covers 3.10 – 3.13).

## Usage

### Estimate from workflow files (offline)

```console
gha-bill scan [PATH] [--default-job-minutes 5] [--plan free|pro|team|enterprise]
                     [--public] [--runs-per-month ci=120] [--prices prices.json] [--json]
```

- `--default-job-minutes` — minutes assumed per job when `timeout-minutes` is absent (default 5).
- `--runs-per-month WORKFLOW=N` — override the run-frequency heuristic (repeatable).
- `--plan` — compare billed minutes against the plan's included minutes.
- `--public` — public repo: standard runners are free, so the included-minutes
  comparison is skipped and the dollar figures are informational only (minutes
  are still the number that matters for quota and for larger runners).
- `--json` — machine-readable output for dashboards.

### Fail the build when CI spend drifts

```yaml
- uses: actions/checkout@v4
- run: pipx install gha-bill
- run: gha-bill check . --budget 25   # exit 1 when the monthly estimate exceeds $25
```

Add a `timeout-minutes` to each job and the estimate stops being an estimate of
duration and starts being a real cap — a matrix change that quietly triples
your spend then fails review instead of arriving as a surprise invoice.

### Measure what actually happened

```console
$ export GITHUB_TOKEN=...        # or put it in ~/.github_token
$ gha-bill history indraoverflow/gha-bill --limit 20
```

`history` reads real job durations from the Actions API, rounds each job up the
way GitHub bills it, and extrapolates 30 days from the sampled window. Estimates
tell you what a change will cost; `history` tells you what it did cost.

## How the estimate is built

| Step | Rule |
|---|---|
| Workflow discovery | every `.github/workflows/*.yml` or `*.yaml` |
| Matrix | cartesian product of list values, plus `include` entries, minus `exclude` |
| Job minutes | `timeout-minutes` when set (capped by `--default-job-minutes`), else the default |
| Billing | each job rounded up to the whole minute, then priced per OS |
| Runs per month | `schedule` counted from its cron over the next 365 days; `push` 60, `pull_request` 20, `workflow_dispatch` 1 |
| Price table | Linux $0.008/min, Windows $0.016/min, macOS $0.080/min (override with `--prices`) |

## Honest limitations

- A static estimate cannot know how long a step really takes. Set
  `timeout-minutes` (bounds are what CI budgets are made of) or use `history`
  for measured numbers. `gha-bill` prints a `note:` line for every assumption it
  had to make — including dynamic matrices and expression-valued `runs-on`.
- Larger runners (`ubuntu-4-core`, `*-8-cores`) are scaled linearly from the
  2-core rate and flagged, because GitHub prices them per core-hour with
  storage billed separately.
- Reusable workflows called with `uses:` at job level have unknowable minutes;
  they are counted as jobs and flagged.

## Roadmap

- [ ] `gha-bill history --by-job` — attribute spend to the individual step that got slow
- [ ] cache hit-rate analysis (cache misses are the most common silent cost)
- [ ] GitHub Action wrapper (`uses: indraoverflow/gha-bill@v1`) that comments the delta on every PR
- [ ] SARIF / step-summary output for org dashboards

## Contributing

Bug reports and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Every change
lands with a test; `ruff check .` and `pytest` must pass.

## License

MIT © Indra Prasetya
