# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-11-06

### Added

- `gha-bill scan` — offline estimate of cost per run and per month for every
  workflow under `.github/workflows`, with matrix expansion, per-OS pricing and
  per-job minute rounding.
- `gha-bill check --budget N` — CI gate that exits 1 when the monthly estimate
  exceeds the budget.
- `gha-bill history owner/name --limit N` — real billed minutes measured from the
  Actions API, extrapolated to 30 days.
- `--json` output for both `scan` and `check`, `--prices` override file, `--plan`
  included-minutes comparison, `--public` free-standard-runner handling.
- Notes on every approximation the estimator had to make (dynamic matrices,
  expression-valued `runs-on`, larger runners, reusable workflow calls).
