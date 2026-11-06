# Contributing to gha-bill

Thanks for taking a look. This project stays small on purpose: one CLI, one
pricing model, no daemon, no telemetry.

## Development

```console
git clone https://github.com/indraoverflow/gha-bill
cd gha-bill
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
ruff check .
pytest
```

## Rules of the house

1. **Every change ships with a test.** The estimator's arithmetic (rounding,
   multipliers, matrix expansion) is where bugs hide, so tests pin the numbers,
   not just the exit codes.
2. **Never invent a price.** If GitHub changes its rates, update
   `src/gha_bill/pricing.py` and bump `PRICES_UPDATED`; the README table must
   match the code.
3. **Be honest about estimates.** Any new approximation must print a `note:` in
   the CLI output and be listed under "Honest limitations" in the README. A
   confident wrong number is worse than a flagged guess.
4. **No new runtime dependencies** beyond PyYAML without discussing it in an
   issue first — install friction is the whole product.

## Pull requests

- Conventional commit titles (`feat:`, `fix:`, `docs:` …).
- Describe the workflow shape that motivated the change; a real `.github`
  snippet is worth more than prose.
- CI must be green: `ruff check .`, `pytest`, and the dogfood `gha-bill check`
  job that measures the project's own CI budget.

## Reporting a wrong estimate

Open an issue with the workflow file (redact secrets) and the number you
expected. Please include `gha-bill scan . --json` output — it carries the
per-job breakdown needed to see whether the bug is in duration, matrix
expansion or pricing.
